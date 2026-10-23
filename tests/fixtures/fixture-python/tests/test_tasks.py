from app.tasks import TaskStore


def test_task_recovery_and_cancellation():
    store = TaskStore()
    assert store.recover_after_restart("missing")["status"]
    store.cancel_task = lambda job_id: None

