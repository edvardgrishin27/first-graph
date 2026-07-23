"""Точка входа: python3 -m first_graph <команда>.

Сам разбор команд живёт в дополнениях (extras/cli.py): это интерфейс запуска,
а не теория графов — как и человек-в-контуре, он вынесен из ядра.
"""

from first_graph.extras.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
