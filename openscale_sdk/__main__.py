"""python -m openscale_sdk validate [folder] | version"""

import sys

from . import __version__
from .manifest import load_manifest


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "help"
    if cmd == "version":
        print(__version__)
        return 0
    if cmd == "validate":
        folder = args[1] if len(args) > 1 else "."
        manifest, errors = load_manifest(folder)
        if errors:
            for e in errors:
                print(f"openscale.yaml: {e}", file=sys.stderr)
            return 1
        print(f"openscale.yaml ok: {manifest['name']} ({manifest['runtime']['language']}, {manifest['runtime']['entrypoint']})")
        return 0
    print("usage: python -m openscale_sdk validate [folder] | version", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
