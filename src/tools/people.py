import logging

from fastmcp import FastMCP

from src.models.user import Person
from src.server import get_db

logger = logging.getLogger(__name__)


def register_people_tools(mcp: FastMCP) -> None:
    """Register people management tools on the MCP server."""

    @mcp.tool
    async def manage_person(
        name: str,
        action: str = "add",
        dietary_restrictions: list[str] | None = None,
        no_alcohol: bool = False,
        notes: str | None = None,
    ) -> str:
        """Add, update, or remove a dining companion.

        Args:
            name: Person's name (case-insensitive matching).
            action: "add" to create/update, "remove" to delete.
            dietary_restrictions: Their restrictions, e.g. ["nut_allergy", "vegan"].
            no_alcohol: True if they don't drink alcohol.
            notes: Any other notes, e.g. "Prefers window seats".

        Returns:
            Confirmation of the action taken.
        """
        db = get_db()

        if action == "remove":
            existing = await db.get_person(name)
            if not existing:
                return f"No person named '{name}' found."
            await db.delete_person(name)
            return f"Removed '{name}' from dining companions."

        if action == "add":
            person = Person(
                name=name,
                dietary_restrictions=dietary_restrictions or [],
                no_alcohol=no_alcohol,
                notes=notes,
            )
            await db.save_person(person)
            parts = [f"Saved '{name}'."]
            if dietary_restrictions:
                parts.append(f"Dietary: {', '.join(dietary_restrictions)}")
            if no_alcohol:
                parts.append("No alcohol.")
            if notes:
                parts.append(f"Notes: {notes}")
            return " ".join(parts)

        return f"Unknown action '{action}'. Use 'add' or 'remove'."

    @mcp.tool
    async def list_people() -> str:
        """List all saved dining companions with their dietary restrictions
        and notes.

        Returns:
            Formatted list of all people and their preferences.
        """
        db = get_db()
        people = await db.get_people()
        if not people:
            return "No dining companions saved yet. Use manage_person to add someone."

        lines: list[str] = []
        for p in people:
            parts = [f"- {p.name}"]
            if p.dietary_restrictions:
                parts.append(f"(dietary: {', '.join(p.dietary_restrictions)})")
            if p.no_alcohol:
                parts.append("(no alcohol)")
            if p.notes:
                parts.append(f"- {p.notes}")
            lines.append(" ".join(parts))
        return "\n".join(lines)
