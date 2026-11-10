"""Ejecución de los scripts vendorizados como subprocesos, con tope de tiempo y avisos periódicos."""
import asyncio
import os
import signal
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings


@dataclass
class Result:
    code: int | None
    timed_out: bool
    log: Path

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.timed_out

    def tail(self, chars: int = 1500) -> str:
        try:
            return self.log.read_text(encoding="utf-8", errors="replace")[-chars:]
        except OSError:
            return ""


def services_dir() -> Path:
    configured = get_settings().services_dir
    # por defecto <repo>/services (este archivo vive en <repo>/apps/worker/worker/)
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[3] / "services"


def script(tool: str, name: str) -> list[str]:
    return [sys.executable, "-u", str(services_dir() / tool / name)]


async def _stop(proc: asyncio.subprocess.Process) -> None:
    """Pide al script que termine guardando su progreso (Ctrl+C); si no responde, lo mata."""
    try:
        if os.name == "nt":
            proc.terminate()
        else:
            proc.send_signal(signal.SIGINT)
        await asyncio.wait_for(proc.wait(), 30)
    except (asyncio.TimeoutError, ProcessLookupError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()


async def run(cmd: list[str], *, log: Path, cwd: Path | None = None, env: dict | None = None,
              timeout: float | None = None, on_tick: Callable[[], Awaitable[None]] | None = None,
              tick: float = 10) -> Result:
    """Corre `cmd` mandando su salida a `log`. Cada `tick` segundos llama a `on_tick` (para publicar
    el progreso). Al pasar `timeout` detiene el proceso y devuelve timed_out=True."""
    log.parent.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout if timeout else None
    with open(log, "ab") as out:
        out.write(("\n$ " + " ".join(os.path.basename(c) if i < 3 else c for i, c in enumerate(cmd)) + "\n").encode())
        out.flush()
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=cwd, env={**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})},
            stdin=asyncio.subprocess.DEVNULL, stdout=out, stderr=asyncio.subprocess.STDOUT)
        try:
            while True:
                wait = tick if deadline is None else max(0.05, min(tick, deadline - loop.time()))
                try:
                    code = await asyncio.wait_for(proc.wait(), wait)
                    return Result(code, False, log)
                except asyncio.TimeoutError:
                    pass
                if on_tick:
                    await on_tick()
                if deadline is not None and loop.time() >= deadline:
                    await _stop(proc)
                    return Result(proc.returncode, True, log)
        except asyncio.CancelledError:  # el worker se está apagando: no dejar el script huérfano
            await _stop(proc)
            raise
