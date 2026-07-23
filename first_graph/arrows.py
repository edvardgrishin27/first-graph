"""Детектор фальшивых стрелок.

Вы напечатали «а потом». Ваш код услышал «жди».

Большинство линейных пайплайнов ждут там, где ждать не нужно: шаг N стоит после
шага N-1 просто потому, что вы набрали их в этом порядке, а не потому, что он
читает его результат. Такое ожидание — чистая потеря времени.

Модуль считает это детерминированно, без всякой модели: по объявленным
входам и выходам шагов строится настоящий граф зависимостей, а всё, что
осталось от порядка набора, помечается как фальшивое ребро.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_DURATION = 1.0


class PipelineError(ValueError):
    """Некорректное описание пайплайна."""


@dataclass(frozen=True)
class PipelineStep:
    """Шаг пайплайна с объявленными входами и выходами.

    reads  — какие ключи состояния шаг читает
    writes — какие ключи состояния шаг пишет
    duration — сколько шаг занимает (в любых единицах: секунды, минуты)
    """

    id: str
    reads: frozenset[str] = frozenset()
    writes: frozenset[str] = frozenset()
    duration: float = DEFAULT_DURATION

    def __post_init__(self) -> None:
        if not self.id:
            raise PipelineError("у шага должен быть непустой id")
        if self.duration < 0:
            raise PipelineError(f"шаг {self.id}: отрицательная длительность")


@dataclass
class Arrow:
    """Стрелка между соседними шагами в том виде, как её написал человек."""

    source: str
    target: str
    real: bool
    carries: frozenset[str] = frozenset()
    cost: float = 0.0
    """Сколько времени стоит это ожидание. У настоящих стрелок — 0."""

    @property
    def verdict(self) -> str:
        if self.real:
            return f"настоящая — переносит: {', '.join(sorted(self.carries))}"
        if self.cost > 0:
            return f"ФАЛЬШИВАЯ и дорогая — это ожидание стоит {self.cost:g}"
        return "фальшивая, но бесплатная — ветка и так укладывается в срок"


@dataclass
class Report:
    """Что нашли и что с этим делать."""

    arrows: list[Arrow] = field(default_factory=list)
    levels: list[list[str]] = field(default_factory=list)
    sequential_time: float = 0.0
    parallel_time: float = 0.0
    unresolved: dict[str, frozenset[str]] = field(default_factory=dict)
    races: dict[str, list[str]] = field(default_factory=dict)
    # служебное для capped_time — заполняет audit(), в отчёт не печатается
    _steps: list["PipelineStep"] = field(default_factory=list, repr=False)
    _deps: dict[str, set[str]] = field(default_factory=dict, repr=False)

    @property
    def fake_arrows(self) -> list[Arrow]:
        return [a for a in self.arrows if not a.real]

    @property
    def costly_arrows(self) -> list[Arrow]:
        """Фальшивые стрелки, которые реально удлиняют работу.

        Остальные фальшивые — на ветке с запасом: данные через них не ходят,
        но и резать их бессмысленно, общий срок не изменится.
        """
        return [a for a in self.arrows if not a.real and a.cost > 0]

    @property
    def speedup(self) -> float:
        if self.parallel_time <= 0:
            return 1.0
        return self.sequential_time / self.parallel_time

    def render(self) -> str:
        lines: list[str] = []
        lines.append("СТРЕЛКИ, КАК ВЫ ИХ НАПИСАЛИ")
        for arrow in self.arrows:
            mark = "✓" if arrow.real else "✗"
            lines.append(f"  {mark} {arrow.source} → {arrow.target}: {arrow.verdict}")

        fake = self.fake_arrows
        costly = self.costly_arrows
        lines.append("")
        if not self.arrows:
            lines.append("ИТОГ: связей между шагами нет")
        else:
            lines.append(f"ИТОГ: фальшивых стрелок {len(fake)} из {len(self.arrows)}")
            lines.append(
                f"      из них реально стоят времени: {len(costly)}"
                + (f" (суммарно {sum(a.cost for a in costly):g})" if costly else "")
            )
            if fake and not costly:
                lines.append("      резать нечего: все они на ветках с запасом")

        if self.unresolved:
            lines.append("")
            lines.append("ВНИМАНИЕ: шаги читают то, что никто до них не записал")
            for step_id, keys in sorted(self.unresolved.items()):
                lines.append(f"  {step_id}: {', '.join(sorted(keys))}")
            lines.append("  (это либо внешний вход, либо забытая зависимость)")

        if self.races:
            lines.append("")
            lines.append("ГОНКА: шаги на одном уровне пишут в одно и то же — кто первый, тот и прав")
            for key, writers in sorted(self.races.items()):
                lines.append(f"  «{key}» пишут одновременно: {', '.join(writers)}")
            lines.append("  (объявите зависимость явно или пусть пишут в разное)")

        lines.append("")
        lines.append("КАК ЭТО ДОЛЖНО ИДТИ НА САМОМ ДЕЛЕ")
        for i, level in enumerate(self.levels, start=1):
            joined = ", ".join(level)
            suffix = "  ← одновременно" if len(level) > 1 else ""
            lines.append(f"  уровень {i}: {joined}{suffix}")

        lines.append("")
        lines.append(f"Было (по очереди):     {self.sequential_time:g}")
        lines.append(f"Стало (по графу):      {self.parallel_time:g}")
        lines.append(f"Ускорение:             {self.speedup:.1f}×")
        return "\n".join(lines)

    def capped_time(self, workers: int) -> float:
        """Сколько займёт работа, если одновременно можно не больше `workers`.

        Идеальный параллелизм — приятное враньё: у Claude Code кап 16 агентов
        сразу, у человека рук ещё меньше. Здесь честный расчёт списочным
        планированием: узел стартует, когда готовы его зависимости И
        освободился работник. Возвращает время окончания последнего узла.
        """
        if workers < 1:
            raise ValueError("работников должно быть не меньше 1")
        return _scheduled_finish(self._steps, self._deps, workers)

    def capped_speedup(self, workers: int) -> float:
        capped = self.capped_time(workers)
        return self.sequential_time / capped if capped > 0 else 1.0


def _validate(steps: list[PipelineStep]) -> None:
    if not steps:
        raise PipelineError("пайплайн пуст")
    seen: set[str] = set()
    for step in steps:
        if step.id in seen:
            raise PipelineError(f"повторяющийся id шага: {step.id}")
        seen.add(step.id)


def _real_dependencies(steps: list[PipelineStep]) -> dict[str, set[str]]:
    """Для каждого шага — множество шагов, чей вывод он действительно читает.

    Читаем ближайшего предшествующего писателя каждого ключа: именно он
    определяет значение, которое шаг увидит.
    """
    deps: dict[str, set[str]] = {step.id: set() for step in steps}
    last_writer: dict[str, str] = {}

    for step in steps:
        for key in step.reads:
            writer = last_writer.get(key)
            if writer is not None:
                deps[step.id].add(writer)
        for key in step.writes:
            last_writer[key] = step.id

    return deps


def _unresolved_reads(steps: list[PipelineStep]) -> dict[str, frozenset[str]]:
    """Ключи, которые шаг читает, хотя до него их никто не писал."""
    missing: dict[str, frozenset[str]] = {}
    written: set[str] = set()
    for step in steps:
        gaps = {key for key in step.reads if key not in written}
        if gaps:
            missing[step.id] = frozenset(gaps)
        written |= set(step.writes)
    return missing


def _levels(steps: list[PipelineStep], deps: dict[str, set[str]]) -> list[list[str]]:
    """Раскладывает шаги по уровням: внутри уровня всё идёт одновременно."""
    depth: dict[str, int] = {}
    for step in steps:  # входной порядок уже топологический
        parents = deps[step.id]
        depth[step.id] = 0 if not parents else max(depth[p] for p in parents) + 1

    levels: list[list[str]] = []
    for step in steps:
        index = depth[step.id]
        while len(levels) <= index:
            levels.append([])
        levels[index].append(step.id)
    return levels


def _critical_path(steps: list[PipelineStep], deps: dict[str, set[str]]) -> float:
    """Длина критического пути — столько займёт правильно разложенный граф."""
    by_id = {step.id: step for step in steps}
    finish: dict[str, float] = {}
    for step in steps:
        start = max((finish[p] for p in deps[step.id]), default=0.0)
        finish[step.id] = start + by_id[step.id].duration
    return max(finish.values(), default=0.0)


def _scheduled_finish(
    steps: list[PipelineStep], deps: dict[str, set[str]], workers: int
) -> float:
    """Время окончания при ограниченном числе работников (списочное планирование).

    Свободный работник берёт готовый узел, что освободился раньше, при равенстве —
    что дольше (снижает хвост). Возвращаем момент, когда закончился последний.
    """
    by_id = {step.id: step for step in steps}
    finish: dict[str, float] = {}
    free_at = [0.0] * workers  # когда освободится каждый работник
    done: set[str] = set()

    def parents_done(sid: str) -> float:
        return max((finish[p] for p in deps[sid]), default=0.0)

    while len(done) < len(steps):
        ready = [s.id for s in steps if s.id not in done and deps[s.id] <= done]
        if not ready:  # цикла быть не должно — вход топологический
            break
        sid = min(ready, key=lambda s: (parents_done(s), -by_id[s].duration))
        w = min(range(workers), key=lambda i: free_at[i])
        finish[sid] = max(parents_done(sid), free_at[w]) + by_id[sid].duration
        free_at[w] = finish[sid]
        done.add(sid)

    return max(finish.values(), default=0.0)


def _races(steps: list[PipelineStep], levels: list[list[str]]) -> dict[str, list[str]]:
    """Шаги на одном уровне, пишущие в один ключ, — гонка за общий ресурс.

    Самый частый источник ложной «независимости»: два шага кажутся
    параллельными, а на деле дерутся за один файл. Результат зависит от того,
    кто успел первым, — и это баг, который проявляется не всегда.
    """
    by_id = {step.id: step for step in steps}
    races: dict[str, list[str]] = {}
    for level in levels:
        if len(level) < 2:
            continue
        writers_of: dict[str, list[str]] = {}
        for sid in level:
            for key in by_id[sid].writes:
                writers_of.setdefault(key, []).append(sid)
        for key, writers in writers_of.items():
            if len(writers) > 1:
                races[key] = writers
    return races


def _cost_of_wait(
    steps: list[PipelineStep], deps: dict[str, set[str]], source: str, target: str
) -> float:
    """Насколько удлинится работа, если оставить это ожидание.

    Считаем в лоб: добавляем зависимость и смотрим, вырос ли критический путь.
    Ноль означает, что стрелка фальшивая, но безвредная — ветка и так
    успевает. Это важное различие: резать стоит только то, что стоит денег.
    """
    было = _critical_path(steps, deps)
    с_ожиданием = {узел: set(родители) for узел, родители in deps.items()}
    с_ожиданием[target].add(source)
    return _critical_path(steps, с_ожиданием) - было


def audit(steps: list[PipelineStep]) -> Report:
    """Главная функция: находит фальшивые стрелки и считает выигрыш."""
    _validate(steps)

    deps = _real_dependencies(steps)

    arrows: list[Arrow] = []
    for previous, current in zip(steps, steps[1:]):
        carried = frozenset(previous.writes & current.reads)
        настоящая = previous.id in deps[current.id]
        arrows.append(
            Arrow(
                source=previous.id,
                target=current.id,
                real=настоящая,
                carries=carried,
                cost=0.0
                if настоящая
                else _cost_of_wait(steps, deps, previous.id, current.id),
            )
        )

    levels = _levels(steps, deps)
    report = Report(
        arrows=arrows,
        levels=levels,
        sequential_time=sum(step.duration for step in steps),
        parallel_time=_critical_path(steps, deps),
        unresolved=_unresolved_reads(steps),
        races=_races(steps, levels),
    )
    # для расчёта с ограничением работников (capped_time) — не в отчёте, служебное
    report._steps = steps
    report._deps = deps
    return report


def from_dicts(raw: list[dict]) -> list[PipelineStep]:
    """Собирает шаги из простых словарей — как их отдаёт YAML или JSON."""
    steps: list[PipelineStep] = []
    for index, item in enumerate(raw):
        if "id" not in item:
            raise PipelineError(f"шаг №{index + 1}: нет поля id")
        steps.append(
            PipelineStep(
                id=str(item["id"]),
                reads=frozenset(item.get("reads", ())),
                writes=frozenset(item.get("writes", ())),
                duration=float(item.get("duration", DEFAULT_DURATION)),
            )
        )
    return steps
