import argparse
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Launch the Streamlit daily energy app with optional input file."
    )
    parser.add_argument("--input", default=None, help="Path to daily energy CSV file")
    parser.add_argument(
        "--server-port", type=int, default=None, help="Optional Streamlit server port"
    )
    args = parser.parse_args()

    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "src/energy_daily_streamlit.py",
    ]

    if args.server_port is not None:
        command.extend(["--server.port", str(args.server_port)])

    if args.input:
        command.extend(["--", "--input", args.input])

    raise SystemExit(subprocess.call(command))


if __name__ == "__main__":
    main()
