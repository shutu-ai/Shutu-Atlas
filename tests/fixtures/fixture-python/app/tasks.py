"""Small fixture for real static evidence tests."""

class TaskStore:
    def __init__(self):
        self.jobs = {}

    async def submit_task(self, job_id: str):
        self.jobs[job_id] = {"status": "running", "progress": 0}
        return job_id

    def cancel_task(self, job_id: str):
        self.jobs[job_id]["status"] = "cancelled"

    def recover_after_restart(self, job_id: str):
        """Persisted checkpoints let an async job resume after restart."""
        return self.jobs.get(job_id, {"status": "restart recovery required"})

