import sys

from calc.evaluator import evaluate

if __name__ == "__main__":
    try:
        print(evaluate(" ".join(sys.argv[1:])))
    except (ValueError, ZeroDivisionError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
