"""``--resume`` matches completed prompts by content, so it must survive a reordered dataset.

The checkpoint's index list describes the dataset order of the run that wrote it; after
content filtering has picked the remaining rows, those stale indices must not veto them.
"""

import json

import batch_runner
from batch_runner import BatchRunner


class _InProcessPool:
    """``multiprocessing.Pool`` surface used by ``_run_pool``, run inline so stubs apply."""

    def __init__(self, processes=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def imap_unordered(self, fn, tasks):
        return (fn(task) for task in tasks)

    def terminate(self):
        pass

    def join(self):
        pass


def _write_dataset(path, prompts):
    path.write_text("".join(json.dumps({"prompt": p}) + "\n" for p in prompts), encoding="utf-8")


def test_resume_runs_remaining_prompts_after_dataset_reorder(tmp_path, monkeypatch):
    ran = []

    def fake_prompt(prompt_index, prompt_data, batch_num, config):
        ran.append(prompt_data["prompt"])
        return {
            "success": True, "prompt_index": prompt_index,
            "trajectory": [{"from": "human", "value": prompt_data["prompt"]}, {"from": "gpt", "value": "ok"}],
            "tool_stats": {}, "reasoning_stats": {"has_any_reasoning": True},
            "completed": True, "partial": False, "api_calls": 1, "toolsets_used": [], "metadata": {},
        }

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["batch_runner.py"])
    monkeypatch.setattr(batch_runner, "Pool", _InProcessPool)
    monkeypatch.setattr(batch_runner, "_process_single_prompt", fake_prompt)
    dataset = tmp_path / "dataset.jsonl"

    # First run completes A and B (dataset indices 0 and 1), then stops.
    _write_dataset(dataset, ["A", "B", "C", "D"])
    BatchRunner(dataset_file=str(dataset), batch_size=2, run_name="reorder", num_workers=1, max_samples=2).run()
    assert ran == ["A", "B"]

    # The dataset is reordered: C and D now sit at the indices the checkpoint recorded.
    _write_dataset(dataset, ["C", "D", "A", "B"])
    ran.clear()
    BatchRunner(dataset_file=str(dataset), batch_size=2, run_name="reorder", num_workers=1).run(resume=True)

    assert sorted(ran) == ["C", "D"]
    merged = (tmp_path / "data" / "reorder" / "trajectories.jsonl").read_text(encoding="utf-8").splitlines()
    assert sorted(json.loads(line)["conversations"][0]["value"] for line in merged) == ["A", "B", "C", "D"]
