from typing import Optional
from pydantic import BaseModel, Field

class AgentState(BaseModel):
    current_phase: str = "smoke_test"
    current_task: str = ""
    last_commit_sha: Optional[str] = None
    ci_run_id: Optional[int] = None
    ci_status: Optional[str] = None      # "in_progress" | "success" | "failure"
    ci_logs: Optional[str] = None
    retry_count: int = 0
    runbook_entries: list[str] = Field(default_factory=list)
    task_complete: bool = False
    needs_human: bool = False
    error_message: Optional[str] = None