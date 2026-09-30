"""Final-video encoding policy. No application state or path imports.

Keep each builder's software command as the fallback, including its audio and timing.
Only final exports opt in; lossless/transparent intermediate encoders are untouched.
"""
from functools import lru_cache
import os
import platform
import subprocess
import time

QUALITY = 75


@lru_cache(maxsize=4)
def hardware_available(ffmpeg):
    if platform.system() != 'Darwin':
        return False
    try:
        result = subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
            'color=s=64x64:r=30', '-frames:v', '2', '-an', '-c:v',
            'h264_videotoolbox', '-allow_sw', '0', '-q:v', str(QUALITY),
            '-pix_fmt', 'yuv420p', '-f', 'null', '-'],
            capture_output=True, text=True, timeout=15)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def hardware_command(command):
    cmd = list(command)
    # Input decoder selections can also use -c:v. Change only the output encoder.
    index = max(i for i, item in enumerate(cmd) if item == '-c:v')
    if cmd[index+1:index+6] != ['libx264', '-preset', 'medium', '-crf', '18']:
        raise ValueError('Final encoding requires the reviewed software profile')
    cmd[index:index+6] = ['-c:v', 'h264_videotoolbox', '-allow_sw', '0',
                         '-q:v', str(QUALITY)]
    return cmd


def run(command, *, runner, label='video'):
    """Preserve the caller's result/exception contract and retry a failed hardware export."""
    # Crop/scale variations can leave a tiny non-square sample aspect ratio. These
    # vertical exports must display as their actual 9:16 canvas in browsers too.
    command = list(command)
    if '-aspect' not in command:
        command[-1:-1] = ['-aspect', '9:16']
    started = time.monotonic()
    use_hardware = (os.environ.get('SG_VIDEO_ENCODER', 'auto') != 'software'
                    and hardware_available(str(command[0])))
    mode = 'hardware' if use_hardware else 'software'
    try:
        result = runner(hardware_command(command) if use_hardware else command)
        failed = getattr(result, 'returncode', 0) != 0
    except RuntimeError:
        if not use_hardware:
            raise
        result = None
        failed = True
    if use_hardware and failed:
        # Builders supply -y, so a partial hardware file is replaced by a full retry.
        print('  Hardware encoding unavailable for this video; retrying with the CPU.', flush=True)
        mode = 'software fallback'
        result = runner(command)
    if getattr(result, 'returncode', 0) == 0:
        print('  timing: %s render %.2fs (%s)' %
              (label, time.monotonic()-started, mode), flush=True)
    return result
