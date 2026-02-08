"""Dev CLI for paper-search. Usage: python -m paper_search <query>"""

from __future__ import annotations

import asyncio
import sys


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m paper_search <query>", file=sys.stderr)
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    try:
        result = asyncio.run(_run(query))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    from paper_search import export_markdown

    print(export_markdown(result))


async def _run(query: str):
    from paper_search import search
    from paper_search.config import load_config

    config = load_config()
    return await search(query, config=config)


if __name__ == "__main__":
    main()
