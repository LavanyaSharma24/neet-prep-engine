"""v0 prototype CLI: type a NEET Biology question, get a verified answer or a
refusal. No voice, no diagrams, no escalation, no LLM, no network calls —
see docs/PRD.md 'Phased scope' for what v0 deliberately excludes.
"""
from refusal import decide
from retrieval import load_items, match


def format_answer(result):
    item = result["item"]
    return (
        f"[VERIFIED] (confidence: {result['confidence']:.2f})\n"
        f"{item['answer_text']}\n"
        f"Source: {item['source']}"
    )


def format_refusal(result):
    return f"[REFUSED] (confidence: {result['confidence']:.2f}) {result['message']}"


def main():
    print("NEET Prep Engine -- v0 prototype (text-only, NEET Biology)")
    print("Type a question, or 'quit' to exit.\n")

    items = load_items()
    while True:
        try:
            query = input("> ").strip()
        except EOFError:
            break

        if not query:
            continue
        if query.lower() in {"quit", "exit"}:
            break

        best_item, confidence = match(query, items)
        result = decide(query, best_item, confidence)

        if result["action"] == "answer":
            print(format_answer(result))
        else:
            print(format_refusal(result))
        print()


if __name__ == "__main__":
    main()
