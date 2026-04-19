# aspexy-or

Serviço HTTP com [OR-Tools](https://developers.google.com/optimization) (CP-SAT) para geração de horários. Usado pelo app [aspexy](https://github.com/coder-gabrielsantos/aspexy) via `POST /solve`.

## Endpoints

- `GET /health` — health check
- `POST /solve` — mesmo JSON que o Next envia (`schoolProfile`, `assignments`, `teacherUnavailability`, `teacherPreference` opcional, `teacherMutexGroups` opcional — lista de `{ "teachers": ["Nome1", "Nome2", ...] }` (no máximo um por slot); legado: `teacherMutexPairs` com `{ "teacherA", "teacherB" }`, etc.). Opcionais: `maxLessonsPerDayPerTeacher` (padrão 6), `teacherMaxLessonsPerDay` (mapa nome → inteiro, sobrescreve o padrão), `maxConsecutiveLessonsPerClass` (0 = desligado; em sequências de slots de aula consecutivos, no máximo N aulas seguidas para a mesma turma).


## Local

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

No app aspexy, defina `ASPEXY_OR_SOLVER_URL=http://127.0.0.1:8000`.

## Railway

1. Crie um serviço a partir deste repositório (Dockerfile).
2. Após o deploy, copie a URL pública (ex.: `https://xxx.up.railway.app`).
3. No aspexy (Vercel ou outro), configure `ASPEXY_OR_SOLVER_URL=https://xxx.up.railway.app` (sem barra no final).

Variável opcional: `CORS_ORIGINS` — lista separada por vírgula ou `*` (padrão).
