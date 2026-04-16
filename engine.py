import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

from ortools.sat.python import cp_model


@dataclass(frozen=True)
class Assignment:
    teacher: str
    subject: str
    class_id: str
    weekly_load: int


class IEMASolver:
    def __init__(
        self,
        board_config: Dict[str, Any],
        assignments: Sequence[Dict[str, Any]],
        teacher_unavailability: Dict[str, Dict[str, List[int]]] | None = None,
        max_daily_same_subject: int = 2,
        time_limit_seconds: float = 10.0,
    ) -> None:
        self.board_config = board_config
        expanded_assignments = self._expand_assignments_input(assignments)
        self.assignments: List[Assignment] = [
            self._normalize_assignment(item) for item in expanded_assignments
        ]
        self.teacher_unavailability = teacher_unavailability or {}
        self.max_daily_same_subject = max_daily_same_subject
        self.time_limit_seconds = time_limit_seconds

        self.config = self.board_config["config"]
        self.days: List[str] = self.config["days"]
        self.time_schema: List[Dict[str, Any]] = sorted(
            self.config["time_schema"], key=lambda x: x["slot_index"]
        )
        self.grid_matrix: Dict[str, List[int]] = self.board_config.get(
            "grid_matrix", self.config.get("grid_matrix", {})
        )

        self.lesson_slots = {
            item["slot_index"] for item in self.time_schema if item.get("type") == "lesson"
        }
        self.valid_slots_by_day: Dict[int, List[int]] = self._build_valid_slots_by_day()

        self.model = cp_model.CpModel()
        self.aula: Dict[Tuple[int, int, int], cp_model.IntVar] = {}
        self.pair_vars: List[cp_model.IntVar] = []

    @staticmethod
    def _expand_assignments_input(raw_assignments: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        expanded: List[Dict[str, Any]] = []

        for raw in raw_assignments:
            teacher = raw.get("teacher")
            if not teacher:
                raise ValueError("Cada item de assignments precisa de 'teacher'.")

            if {"subject", "class_id", "weekly_load"}.issubset(raw.keys()):
                expanded.append(
                    {
                        "teacher": teacher,
                        "subject": raw["subject"],
                        "class_id": str(raw["class_id"]),
                        "weekly_load": raw["weekly_load"],
                    }
                )
                continue

            grouped = raw.get("assignments")
            if isinstance(grouped, list):
                for item in grouped:
                    subject = item.get("subject")
                    weekly_load = item.get("weekly_load")
                    class_ids = item.get("class_ids")

                    if subject is None or weekly_load is None or class_ids is None:
                        raise ValueError(
                            f"Formato inválido para professor '{teacher}': "
                            "cada assignment precisa de subject, class_ids e weekly_load."
                        )

                    if isinstance(class_ids, (str, int)):
                        class_ids = [class_ids]

                    if not isinstance(class_ids, list) or not class_ids:
                        raise ValueError(
                            f"Formato inválido para professor '{teacher}' em '{subject}': "
                            "class_ids deve ser lista não vazia."
                        )

                    for class_id in class_ids:
                        expanded.append(
                            {
                                "teacher": teacher,
                                "subject": subject,
                                "class_id": str(class_id),
                                "weekly_load": weekly_load,
                            }
                        )
                continue

            raise ValueError(
                f"Item de assignments inválido para professor '{teacher}'. "
                "Use formato atomico (subject/class_id/weekly_load) ou agrupado (assignments)."
            )

        return expanded

    @staticmethod
    def _normalize_assignment(raw: Dict[str, Any]) -> Assignment:
        teacher = raw["teacher"]
        subject = raw["subject"]
        class_id = str(raw["class_id"])
        weekly_load = int(raw["weekly_load"])
        if weekly_load <= 0:
            raise ValueError(f"Carga horaria invalida para {teacher}/{subject}: {weekly_load}")
        return Assignment(
            teacher=teacher,
            subject=subject,
            class_id=class_id,
            weekly_load=weekly_load,
        )

    def _build_valid_slots_by_day(self) -> Dict[int, List[int]]:
        valid_slots_by_day: Dict[int, List[int]] = {}
        for day_idx in range(len(self.days)):
            day_key = str(day_idx)
            grid_slots = self.grid_matrix.get(day_key, [])
            valid_slots_by_day[day_idx] = sorted(
                slot for slot in grid_slots if slot in self.lesson_slots
            )
        return valid_slots_by_day

    def _build_variables(self) -> None:
        for a_idx, _assignment in enumerate(self.assignments):
            for day_idx in range(len(self.days)):
                for slot in self.valid_slots_by_day[day_idx]:
                    name = f"aula_a{a_idx}_d{day_idx}_s{slot}"
                    self.aula[(a_idx, day_idx, slot)] = self.model.NewBoolVar(name)

    def _add_uniqueness_constraints(self) -> None:
        all_teachers = sorted({a.teacher for a in self.assignments})
        all_classes = sorted({a.class_id for a in self.assignments})

        for day_idx in range(len(self.days)):
            for slot in self.valid_slots_by_day[day_idx]:
                for teacher in all_teachers:
                    vars_teacher_slot = [
                        self.aula[(a_idx, day_idx, slot)]
                        for a_idx, assignment in enumerate(self.assignments)
                        if assignment.teacher == teacher and (a_idx, day_idx, slot) in self.aula
                    ]
                    if vars_teacher_slot:
                        self.model.Add(sum(vars_teacher_slot) <= 1)

                for class_id in all_classes:
                    vars_class_slot = [
                        self.aula[(a_idx, day_idx, slot)]
                        for a_idx, assignment in enumerate(self.assignments)
                        if assignment.class_id == class_id and (a_idx, day_idx, slot) in self.aula
                    ]
                    if vars_class_slot:
                        self.model.Add(sum(vars_class_slot) <= 1)

    def _add_weekly_load_constraints(self) -> None:
        for a_idx, assignment in enumerate(self.assignments):
            vars_assignment = [
                self.aula[(a_idx, day_idx, slot)]
                for day_idx in range(len(self.days))
                for slot in self.valid_slots_by_day[day_idx]
                if (a_idx, day_idx, slot) in self.aula
            ]
            self.model.Add(sum(vars_assignment) == assignment.weekly_load)

    def _add_daily_limit_constraints(self) -> None:
        grouped_by_subject_class: Dict[Tuple[str, str], List[int]] = defaultdict(list)
        for a_idx, assignment in enumerate(self.assignments):
            grouped_by_subject_class[(assignment.subject, assignment.class_id)].append(a_idx)

        for day_idx in range(len(self.days)):
            for (_subject, _class_id), assignment_indexes in grouped_by_subject_class.items():
                vars_day = [
                    self.aula[(a_idx, day_idx, slot)]
                    for a_idx in assignment_indexes
                    for slot in self.valid_slots_by_day[day_idx]
                    if (a_idx, day_idx, slot) in self.aula
                ]
                if vars_day:
                    self.model.Add(sum(vars_day) <= self.max_daily_same_subject)

    def _add_teacher_unavailability_constraints(self) -> None:
        for a_idx, assignment in enumerate(self.assignments):
            teacher_blocked = self.teacher_unavailability.get(assignment.teacher, {})
            for day_str, blocked_slots in teacher_blocked.items():
                try:
                    day_idx = int(day_str)
                except ValueError:
                    continue
                for slot in blocked_slots:
                    key = (a_idx, day_idx, slot)
                    if key in self.aula:
                        self.model.Add(self.aula[key] == 0)

    def _add_consecutive_pair_preference(self) -> None:
        for a_idx, _assignment in enumerate(self.assignments):
            for day_idx in range(len(self.days)):
                slots = self.valid_slots_by_day[day_idx]
                for i in range(len(slots) - 1):
                    s1, s2 = slots[i], slots[i + 1]
                    if s2 != s1 + 1:
                        continue

                    x1 = self.aula[(a_idx, day_idx, s1)]
                    x2 = self.aula[(a_idx, day_idx, s2)]
                    pair = self.model.NewBoolVar(f"pair_a{a_idx}_d{day_idx}_s{s1}_{s2}")
                    self.model.Add(pair <= x1)
                    self.model.Add(pair <= x2)
                    self.model.Add(pair >= x1 + x2 - 1)
                    self.pair_vars.append(pair)

        if self.pair_vars:
            self.model.Maximize(sum(self.pair_vars))

    def _build_model(self) -> None:
        self._build_variables()
        self._add_uniqueness_constraints()
        self._add_weekly_load_constraints()
        self._add_daily_limit_constraints()
        self._add_teacher_unavailability_constraints()
        self._add_consecutive_pair_preference()

    def _extract_solution(self, solver: cp_model.CpSolver, status: int) -> Dict[str, Any]:
        status_name = solver.StatusName(status)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return {
                "school_id": self.board_config.get("school_id"),
                "status": status_name,
                "days": [],
                "allocations": [],
                "message": "Nenhuma solucao viavel foi encontrada.",
            }

        allocation_by_day_slot: Dict[Tuple[int, int], List[Dict[str, Any]]] = defaultdict(list)
        flat_allocations: List[Dict[str, Any]] = []

        for (a_idx, day_idx, slot), var in self.aula.items():
            if solver.BooleanValue(var):
                assignment = self.assignments[a_idx]
                alloc = {
                    "teacher": assignment.teacher,
                    "subject": assignment.subject,
                    "class_id": assignment.class_id,
                    "day_index": day_idx,
                    "day_name": self.days[day_idx],
                    "slot_index": slot,
                }
                allocation_by_day_slot[(day_idx, slot)].append(alloc)
                flat_allocations.append(alloc)

        days_payload: List[Dict[str, Any]] = []
        for day_idx, day_name in enumerate(self.days):
            valid_slots = set(self.valid_slots_by_day[day_idx])
            slots_payload: List[Dict[str, Any]] = []

            for schema_item in self.time_schema:
                slot_index = schema_item["slot_index"]
                slot_type = schema_item.get("type", "lesson")
                is_available = slot_type == "lesson" and slot_index in valid_slots
                slot_allocations = sorted(
                    allocation_by_day_slot.get((day_idx, slot_index), []),
                    key=lambda x: x["class_id"],
                )
                slots_payload.append(
                    {
                        "slot_index": slot_index,
                        "type": slot_type,
                        "enabled": is_available,
                        "assignment": slot_allocations[0] if len(slot_allocations) == 1 else None,
                        "assignments": slot_allocations,
                    }
                )

            days_payload.append(
                {
                    "day_index": day_idx,
                    "day_name": day_name,
                    "slots": slots_payload,
                }
            )

        result: Dict[str, Any] = {
            "school_id": self.board_config.get("school_id"),
            "status": status_name,
            "days": days_payload,
            "allocations": sorted(
                flat_allocations, key=lambda x: (x["day_index"], x["slot_index"], x["class_id"])
            ),
        }
        if self.pair_vars:
            result["pair_preference_score"] = int(solver.ObjectiveValue())
        return result

    def solve(self) -> Dict[str, Any]:
        self._build_model()
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.time_limit_seconds
        solver.parameters.num_search_workers = 8
        status = solver.Solve(self.model)
        return self._extract_solution(solver, status)


def run_solve(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Executa o solver a partir do mesmo JSON que o app Next envia."""
    board = payload.get("schoolProfile")
    assignments = payload.get("assignments")
    teacher_unavailability = payload.get("teacherUnavailability", {})
    max_daily_same_subject = int(payload.get("maxDailySameSubject", 2))
    time_limit_seconds = float(payload.get("timeLimitSeconds", 10.0))

    if not isinstance(board, dict):
        raise ValueError("Campo 'schoolProfile' é obrigatório.")
    if not isinstance(assignments, list):
        raise ValueError("Campo 'assignments' deve ser uma lista.")
    if not isinstance(teacher_unavailability, dict):
        teacher_unavailability = {}

    solver = IEMASolver(
        board_config=board,
        assignments=assignments,
        teacher_unavailability=teacher_unavailability,
        max_daily_same_subject=max_daily_same_subject,
        time_limit_seconds=time_limit_seconds,
    )
    return solver.solve()


def main() -> int:
    try:
        raw_input = sys.stdin.read()
        payload = json.loads(raw_input) if raw_input else {}
        result = run_solve(payload)
        sys.stdout.write(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:  # pragma: no cover
        error_payload = {"error": str(exc)}
        sys.stdout.write(json.dumps(error_payload, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
