#!/usr/bin/env python3
"""Project entry point for the packaged, identity-free Hi846 OTP decoder."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parents[1] / 'aports/temp/pdx246-camera-calibration/hi846_otp.py'),run_name='__main__')
