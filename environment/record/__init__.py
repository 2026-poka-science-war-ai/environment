import logging
import struct
import subprocess
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Any, Iterable

import PyNvVideoCodec
from wii_arena.dlpack import DlpackDeviceType
from wii_arena.dolphin import DolphinFrameBuffer

_LOGGER = logging.getLogger(__name__)

_PIXEL_FORMATS: dict[int, str] = {
    37: "ABGR",  # VK_FORMAT_R8G8B8A8_UNORM
    43: "ABGR",  # VK_FORMAT_R8G8B8A8_SRGB
    44: "ARGB",  # VK_FORMAT_B8G8R8A8_UNORM
    50: "ARGB",  # VK_FORMAT_B8G8R8A8_SRGB
}


class Recorder:
    def __init__(
        self,
        video_file: Path,
        frame_rate: int = 60,
        video_codec: str = "h264",
    ) -> None:
        self._video_file = video_file
        self._frame_rate = frame_rate
        self._video_codec = video_codec
        self._encoder: Any | None = None
        self._process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> "Recorder":
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._process is None:
            return
        encoder, self._encoder = self._encoder, None
        process, self._process = self._process, None
        assert process.stdin is not None
        if encoder is not None:
            for packet in encoder.EndEncode():
                process.stdin.write(bytes(packet["data"]))
        process.stdin.close()
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"ffmpeg exited with return code {return_code}.")
        _LOGGER.info("Saved recording to %s", self._video_file)

    def record(self, frames: Iterable[DolphinFrameBuffer]) -> None:
        for frame in frames:
            self.submit(frame)

    def submit(self, frame: DolphinFrameBuffer) -> None:
        pixels = _frame_to_cuda_array(frame)
        if self._encoder is None or self._process is None:
            self._encoder = self._create_encoder(frame)
            self._process = self._spawn_ffmpeg()
            _LOGGER.info(
                "Recording %dx%d video at %d fps to %s",
                frame.width,
                frame.height,
                self._frame_rate,
                self._video_file,
            )
        assert self._process.stdin is not None
        for packet in self._encoder.Encode(_CudaFrame(pixels)):
            self._process.stdin.write(bytes(packet["data"]))

    def _create_encoder(self, frame: DolphinFrameBuffer) -> Any:
        pixel_format = _PIXEL_FORMATS.get(frame.frame_format)
        if pixel_format is None:
            raise ValueError(
                f"Unsupported frame format {frame.frame_format}. "
                f"Supported formats are {sorted(_PIXEL_FORMATS)}."
            )
        return PyNvVideoCodec.CreateEncoder(
            frame.width,
            frame.height,
            pixel_format,
            False,
            codec=self._video_codec,
            fps=self._frame_rate,
        )

    def _spawn_ffmpeg(self) -> subprocess.Popen[bytes]:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            self._video_codec,
            "-framerate",
            str(self._frame_rate),
            "-i",
            "-",
            "-c:v",
            "copy",
            str(self._video_file),
        ]
        return subprocess.Popen(command, stdin=subprocess.PIPE)


class _CudaFrame:
    # PyNvVideoCodec dispatches device input only via a `cuda()` method.
    def __init__(self, array: Any) -> None:
        self._array = array

    def cuda(self) -> Any:
        return self._array


def _frame_to_cuda_array(frame: DolphinFrameBuffer) -> Any:
    device_type, _ = frame.__dlpack_device__()
    if device_type != DlpackDeviceType.CUDA:
        raise RuntimeError(
            "NVENC recording requires frame buffers on a CUDA device, "
            f"got {DlpackDeviceType(device_type).name}."
        )
    try:
        import cupy
    except ImportError as error:
        raise RuntimeError(
            "cupy is required to read frame buffers from device "
            f"{DlpackDeviceType(device_type).name}."
        ) from error
    return cupy.ascontiguousarray(cupy.from_dlpack(frame)[:, : frame.width, :])


_AUDIO_DUMP_CONTAINER_DIRECTORY = "/dolphin-user/Dump/Audio"


def find_audio_dumps(directory: Path) -> list[Path]:
    return sorted(directory.glob("*dump.wav"))


def dolphin_audio_dump_arguments() -> list[str]:
    # Headless has no audio device, and silence still has to advance the dump.
    return [
        "--config=Dolphin.DSP.Backend=No Audio Output",
        "--config=Dolphin.DSP.DumpAudio=True",
        "--config=Dolphin.DSP.DumpAudioSilent=True",
    ]


def audio_dump_volume(host_directory: Path) -> dict[str, dict[str, str]]:
    return {
        str(host_directory): {"bind": _AUDIO_DUMP_CONTAINER_DIRECTORY, "mode": "rw"}
    }


def _pci_address(bus_id: str) -> tuple[int, int, int]:
    fields = bus_id.strip().split(":")
    device, function = fields[-1].split(".")
    return int(fields[-2], 16), int(device, 16), int(function)


def cuda_pinned_gpu() -> str:
    import cupy

    device = cupy.cuda.runtime.deviceGetPCIBusId(cupy.cuda.runtime.getDevice())
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=uuid,pci.bus_id", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in result.stdout.splitlines():
        uuid, bus_id = (field.strip() for field in line.split(","))
        if _pci_address(bus_id) == _pci_address(device):
            return uuid
    raise RuntimeError(f"No GPU matches the CUDA device at {device}.")


def _finalized_wav_copy(wav_file: Path, destination: Path) -> Path:
    # The container is force-removed before Dolphin backfills the RIFF sizes.
    file_size = wav_file.stat().st_size
    if file_size < 44:
        raise RuntimeError(f"Audio dump {wav_file} is too small ({file_size} bytes).")
    data = bytearray(wav_file.read_bytes())
    if data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise RuntimeError(f"{wav_file} is not a RIFF/WAVE file.")
    if data[36:40] == b"data":
        struct.pack_into("<I", data, 4, file_size - 8)
        struct.pack_into("<I", data, 40, file_size - 44)
    destination.write_bytes(data)
    return destination


def _probe_duration(media_file: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_file),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def mux(video_file: Path, audio_files: list[Path], output_file: Path) -> None:
    if not audio_files:
        raise ValueError("mux() requires at least one audio file.")

    video_duration = _probe_duration(video_file)

    with tempfile.TemporaryDirectory() as work_directory:
        prepared: list[tuple[Path, float]] = []
        for index, dump in enumerate(audio_files):
            repaired = _finalized_wav_copy(dump, Path(work_directory) / f"{index}.wav")
            prepared.append((repaired, _probe_duration(repaired)))

        _LOGGER.info(
            "Muxing video=%.3fs + %d audio dump(s) %s -> %s",
            video_duration,
            len(prepared),
            [f"{duration:.3f}s" for _, duration in prepared],
            output_file,
        )

        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        command += ["-i", str(video_file)]
        # Dumps cover the whole session, the video only its tail.
        for repaired, duration in prepared:
            seek = max(0.0, duration - video_duration)
            command += ["-ss", f"{seek:.6f}", "-i", str(repaired)]

        inputs = "".join(f"[{index + 1}:a]" for index in range(len(prepared)))
        subprocess.run(
            command
            + [
                "-filter_complex",
                f"{inputs}amix=inputs={len(prepared)}:normalize=0[audio]",
                "-map",
                "0:v:0",
                "-map",
                "[audio]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                str(output_file),
            ],
            check=True,
        )
    _LOGGER.info("Saved muxed recording to %s", output_file)
