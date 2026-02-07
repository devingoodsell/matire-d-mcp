import logging

from fastmcp import FastMCP

from src.models.user import Group
from src.server import get_db

logger = logging.getLogger(__name__)


def register_group_tools(mcp: FastMCP) -> None:
    """Register group management tools on the MCP server."""

    @mcp.tool
    async def manage_group(
        group_name: str,
        action: str = "add",
        members: list[str] | None = None,
    ) -> str:
        """Create, update, or remove a named group of dining companions.

        Args:
            group_name: Name for the group, e.g. "work_team", "family".
            action: "add" to create/update, "remove" to delete the group.
            members: List of people names (must already be saved via manage_person).

        Returns:
            Confirmation with group details and merged dietary restrictions.
        """
        db = get_db()

        if action == "remove":
            existing = await db.get_group(group_name)
            if not existing:
                return f"No group named '{group_name}' found."
            await db.delete_group(group_name)
            return f"Removed group '{group_name}'."

        if action == "add":
            if not members:
                return "Members list is required when creating a group."

            # Validate all members exist and collect their IDs
            member_ids: list[int] = []
            not_found: list[str] = []
            for member_name in members:
                person = await db.get_person(member_name)
                if person and person.id is not None:
                    member_ids.append(person.id)
                else:
                    not_found.append(member_name)

            if not_found:
                return (
                    f"Cannot create group: these people are not saved yet: "
                    f"{', '.join(not_found)}. "
                    f"Use manage_person to add them first."
                )

            group = Group(name=group_name, member_ids=member_ids)
            await db.save_group(group)

            # Get merged dietary restrictions
            restrictions = await db.get_group_dietary_restrictions(group_name)
            parts = [
                f"Group '{group_name}' saved with members: "
                f"{', '.join(members)}."
            ]
            if restrictions:
                parts.append(
                    f"Merged dietary restrictions: {', '.join(restrictions)}"
                )
            return " ".join(parts)

        return f"Unknown action '{action}'. Use 'add' or 'remove'."

    @mcp.tool
    async def list_groups() -> str:
        """List all saved groups with their members and merged dietary
        restrictions.

        Returns:
            Formatted list of groups with member details.
        """
        db = get_db()
        groups = await db.get_groups()
        if not groups:
            return "No groups saved yet. Use manage_group to create one."

        lines: list[str] = []
        for g in groups:
            restrictions = await db.get_group_dietary_restrictions(g.name)
            parts = [f"- {g.name}: {', '.join(g.member_names)}"]
            if restrictions:
                parts.append(f"  Dietary: {', '.join(restrictions)}")
            lines.append("\n".join(parts))
        return "\n".join(lines)
