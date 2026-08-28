"""Allow running the evaluation harness via: python -m lobby_attendance evaluate"""

import sys


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "evaluate":
        from .evaluate import main as evaluate_main
        evaluate_main(sys.argv[2:])
    elif len(sys.argv) >= 2 and sys.argv[1] == "serve":
        # Convenience: start the Flask dev server
        import subprocess
        subprocess.run(
            [sys.executable, "-m", "flask", "--app", "lobby_attendance.api:create_app", "run"]
            + sys.argv[2:],
            check=False,
        )
    else:
        print("Usage:")
        print("  python -m lobby_attendance evaluate [OPTIONS]")
        print("  python -m lobby_attendance serve [FLASK OPTIONS]")
        print("")
        print("Run 'python -m lobby_attendance evaluate --help' for evaluation options.")
        sys.exit(1)


if __name__ == "__main__":
    main()
