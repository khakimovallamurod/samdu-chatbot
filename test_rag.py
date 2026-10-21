"""Tezkor tekshiruv: python test_rag.py "Savol matni" """
import sys

import rag


def main():
    q = " ".join(sys.argv[1:]) or "SamDU rektori kim?"
    print(f"Savol: {q}\n")
    res = rag.answer(q)
    print(res["answer"])
    print(f"\nManbalar: {', '.join(s['title'] for s in res['sources']) or '-'}")
    print(f"Vaqt: {res['latency_ms']} ms (kesh: {res['cached']})")


if __name__ == "__main__":
    main()
