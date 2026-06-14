"""One-shot: delete leftover per-product indexes from earlier testing, then
prepare the new shared `productiq-knowledge` index. Safe to re-run."""
import asyncio
import sys
sys.path.insert(0, ".")

from app.moss_service import client, list_indexes, delete_index, ensure_shared_index, SHARED_INDEX


async def main():
    names = await list_indexes()
    print(f"Found {len(names)} existing indexes:")
    for n in names:
        print(f"  - {n}")

    to_delete = [n for n in names if n.startswith("prod-")]
    for n in to_delete:
        print(f"deleting legacy index: {n}")
        await delete_index(n)

    print(f"\nEnsuring shared index '{SHARED_INDEX}'...")
    await ensure_shared_index()
    print("Done.")

    remaining = await list_indexes()
    print(f"\nIndexes after cleanup ({len(remaining)}):")
    for n in remaining:
        print(f"  - {n}")


if __name__ == "__main__":
    asyncio.run(main())
