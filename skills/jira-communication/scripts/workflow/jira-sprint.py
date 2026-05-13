#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "atlassian-python-api>=4.0.0,<5",
#     "click>=8.1.0,<9",
# ]
# ///
"""Jira sprint operations - list sprints and get sprint issues."""

import sys
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# Shared library import (TR1.1.1 - PYTHONPATH approach)
# ═══════════════════════════════════════════════════════════════════════════════
_script_dir = Path(__file__).parent
_lib_path = _script_dir.parent / "lib"
if _lib_path.exists():
    sys.path.insert(0, str(_lib_path.parent))

import click
from lib.client import LazyJiraClient
from lib.output import error, format_output, format_table, resolve_board_id, success

# ═══════════════════════════════════════════════════════════════════════════════
# CLI Definition
# ═══════════════════════════════════════════════════════════════════════════════


@click.group()
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.option("--quiet", "-q", is_flag=True, help="Minimal output")
@click.option("--env-file", type=click.Path(), help="Environment file path")
@click.option("--profile", "-P", help="Jira profile name from ~/.jira/profiles.json")
@click.option("--debug", is_flag=True, help="Show debug information on errors")
@click.pass_context
def cli(ctx, output_json: bool, quiet: bool, env_file: str | None, profile: str | None, debug: bool):
    """Jira sprint operations.

    List sprints and get sprint issues from agile boards.
    """
    ctx.ensure_object(dict)
    ctx.obj["json"] = output_json
    ctx.obj["quiet"] = quiet
    ctx.obj["debug"] = debug
    ctx.obj["client"] = LazyJiraClient(env_file=env_file, profile=profile)


@cli.command("list")
@click.argument("board_id", type=int, required=False, default=None)
@click.option("--state", "-s", type=click.Choice(["active", "future", "closed"]), help="Filter by sprint state")
@click.pass_context
def list_sprints(ctx, board_id: int | None, state: str | None):
    """List sprints for a board.

    BOARD_ID: The Jira agile board ID

    Examples:

      jira-sprint list 42

      jira-sprint list 42 --state active

      jira-sprint list 42 --state future --json
    """
    client = ctx.obj["client"]
    board_id = resolve_board_id(board_id)

    try:
        # Get sprints using agile API
        params = {}
        if state:
            params["state"] = state

        sprints: list[dict] = []
        start_at = 0
        while True:
            page_params = dict(params)
            page_params["startAt"] = start_at
            response = client.get(f"rest/agile/1.0/board/{board_id}/sprint", params=page_params) or {}
            values = response.get("values", []) or []
            sprints.extend(values)
            is_last = bool(response.get("isLast"))
            if is_last or not values:
                break
            start_at += len(values)

        if ctx.obj["json"]:
            format_output(sprints, as_json=True)
        elif ctx.obj["quiet"]:
            for s in sprints:
                print(s.get("id", ""))
        else:
            if not sprints:
                print(f"No sprints found for board {board_id}")
                if state:
                    print(f"  (filtered by state: {state})")
            else:
                print(f"Sprints for board {board_id}:\n")
                rows = []
                for s in sprints:
                    start = s.get("startDate", "")[:10] if s.get("startDate") else "-"
                    end = s.get("endDate", "")[:10] if s.get("endDate") else "-"
                    rows.append(
                        {
                            "ID": s.get("id", ""),
                            "Name": s.get("name", ""),
                            "State": s.get("state", ""),
                            "Start": start,
                            "End": end,
                        }
                    )
                print(format_table(rows, ["ID", "Name", "State", "Start", "End"]))

    except Exception as e:
        if ctx.obj["debug"]:
            raise
        error(f"Failed to get sprints for board {board_id}: {e}")
        sys.exit(1)


@cli.command()
@click.argument("sprint_id", type=int)
@click.option("--fields", "-f", default="key,summary,status,assignee", help="Comma-separated fields to return")
@click.pass_context
def issues(ctx, sprint_id: int, fields: str):
    """Get issues in a sprint.

    SPRINT_ID: The sprint ID

    Examples:

      jira-sprint issues 123

      jira-sprint issues 123 --fields key,summary,status,priority
    """
    client = ctx.obj["client"]

    try:
        field_list = [f.strip() for f in fields.split(",")]

        # Get sprint issues using agile API
        response = client.get(f"rest/agile/1.0/sprint/{sprint_id}/issue", params={"fields": ",".join(field_list)})
        issues_list = response.get("issues", [])

        if ctx.obj["json"]:
            format_output(issues_list, as_json=True)
        elif ctx.obj["quiet"]:
            for issue in issues_list:
                print(issue["key"])
        else:
            if not issues_list:
                print(f"No issues in sprint {sprint_id}")
            else:
                print(f"Issues in sprint {sprint_id} ({len(issues_list)} total):\n")
                rows = []
                for issue in issues_list:
                    row = {"key": issue["key"]}
                    issue_fields = issue.get("fields", {})
                    for f in field_list:
                        if f == "key":
                            continue
                        value = issue_fields.get(f)
                        if isinstance(value, dict):
                            value = value.get("name") or value.get("displayName") or str(value)
                        row[f] = value or "-"
                    rows.append(row)
                columns = ["key"] + [f for f in field_list if f != "key"]
                print(format_table(rows, columns))

    except Exception as e:
        if ctx.obj["debug"]:
            raise
        error(f"Failed to get issues for sprint {sprint_id}: {e}")
        sys.exit(1)


@cli.command()
@click.argument("board_id", type=int, required=False, default=None)
@click.pass_context
def current(ctx, board_id: int | None):
    """Get the current active sprint for a board.

    BOARD_ID: The Jira agile board ID

    Examples:

      jira-sprint current 42
    """
    client = ctx.obj["client"]
    board_id = resolve_board_id(board_id)

    try:
        # Get active sprints (first page is enough for "current")
        response = client.get(f"rest/agile/1.0/board/{board_id}/sprint", params={"state": "active"}) or {}
        sprints = response.get("values", []) or []

        if not sprints:
            print(f"No active sprint for board {board_id}")
            return

        sprint = sprints[0]  # Get first active sprint

        if ctx.obj["json"]:
            format_output(sprint, as_json=True)
        elif ctx.obj["quiet"]:
            print(sprint.get("id", ""))
        else:
            print(f"Current sprint for board {board_id}:\n")
            print(f"  ID: {sprint.get('id', '')}")
            print(f"  Name: {sprint.get('name', '')}")
            print(f"  Goal: {sprint.get('goal', '-')}")
            start = sprint.get("startDate", "")[:10] if sprint.get("startDate") else "-"
            end = sprint.get("endDate", "")[:10] if sprint.get("endDate") else "-"
            print(f"  Start: {start}")
            print(f"  End: {end}")

    except Exception as e:
        if ctx.obj["debug"]:
            raise
        error(f"Failed to get current sprint for board {board_id}: {e}")
        sys.exit(1)


@cli.command()
@click.argument("sprint_id", type=int)
@click.argument("issues", nargs=-1, required=True)
@click.option("--dry-run", is_flag=True, help="Show what would be done without making changes")
@click.pass_context
def add(ctx, sprint_id: int, issues: tuple[str, ...], dry_run: bool):
    """Add one or more issues to a sprint.

    SPRINT_ID: The sprint ID
    ISSUES: One or more issue keys (e.g. PROJ-123 PROJ-456)

    Examples:

      jira-sprint add 42 PROJ-123

      jira-sprint add 42 PROJ-123 PROJ-456 PROJ-789

      jira-sprint add 42 PROJ-123 --dry-run
    """
    client = ctx.obj["client"]
    keys = list(issues)

    if dry_run:
        format_output({"dry_run": True, "sprint_id": sprint_id, "issues": keys}, as_json=ctx.obj["output_json"])
        if not ctx.obj["output_json"] and not ctx.obj["quiet"]:
            print(f"Would add {len(keys)} issue(s) to sprint {sprint_id}: {', '.join(keys)}")
        return

    try:
        client.post(
            f"rest/agile/1.0/sprint/{sprint_id}/issue",
            data={"issues": keys},
        )
        result = {"sprint_id": sprint_id, "issues": keys, "action": "added"}
        if ctx.obj["output_json"]:
            format_output(result, as_json=True)
        elif not ctx.obj["quiet"]:
            success(f"Added {len(keys)} issue(s) to sprint {sprint_id}: {', '.join(keys)}")
    except Exception as e:
        if ctx.obj["debug"]:
            raise
        error(f"Failed to add issues to sprint {sprint_id}: {e}")
        sys.exit(1)


@cli.command()
@click.argument("issues", nargs=-1, required=True)
@click.option("--dry-run", is_flag=True, help="Show what would be done without making changes")
@click.pass_context
def remove(ctx, issues: tuple[str, ...], dry_run: bool):
    """Remove one or more issues from their current sprint (move to backlog).

    ISSUES: One or more issue keys (e.g. PROJ-123 PROJ-456)

    Examples:

      jira-sprint remove PROJ-123

      jira-sprint remove PROJ-123 PROJ-456

      jira-sprint remove PROJ-123 --dry-run
    """
    client = ctx.obj["client"]
    keys = list(issues)

    if dry_run:
        format_output({"dry_run": True, "issues": keys}, as_json=ctx.obj["output_json"])
        if not ctx.obj["output_json"] and not ctx.obj["quiet"]:
            print(f"Would remove {len(keys)} issue(s) from their sprint: {', '.join(keys)}")
        return

    try:
        client.post(
            "rest/agile/1.0/backlog/issue",
            data={"issues": keys},
        )
        result = {"issues": keys, "action": "moved_to_backlog"}
        if ctx.obj["output_json"]:
            format_output(result, as_json=True)
        elif not ctx.obj["quiet"]:
            success(f"Moved {len(keys)} issue(s) to backlog: {', '.join(keys)}")
    except Exception as e:
        if ctx.obj["debug"]:
            raise
        error(f"Failed to remove issues from sprint: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli()
