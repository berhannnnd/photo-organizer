"""Opt-in polling worker entrypoint."""

import argparse

from photo_organizer.library.lifecycle import watch_loop

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--state", required=True)
    a = p.parse_args()
    watch_loop(a.state)
