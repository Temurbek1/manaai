"""One conversational entry point with idempotent handoff to durable analysis."""

from uuid import NAMESPACE_URL, uuid5

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.chat_service import OperationChatService
from app.mana_operation_ai.application.goal_service import OperationGoalService
from app.mana_operation_ai.domain.chat import MessageCreate
from app.mana_operation_ai.domain.goals import GoalConversationTurn, GoalCreate
from app.mana_operation_ai.domain.workspace import WorkspaceTurn


class OperationWorkspaceService:
    def __init__(self, chats: OperationChatService, goals: OperationGoalService) -> None:
        self._chats = chats
        self._goals = goals

    async def send(self, owner: str, topic_id: str, request: MessageCreate) -> WorkspaceTurn:
        if not (
            self._goals.availability.enabled and self._goals.availability.agent_workspace_enabled
        ):
            raise ChatError("Рабочий режим агента пока отключён.", 503)
        if request.execution_mode != "agent":
            raise ChatError("Рабочий API требует агентный режим.", 422)
        await self._goals._access(owner)
        goals = await self._goals.list_goals(owner, topic_id)
        request_id = uuid5(NAMESPACE_URL, f"mana-workspace:{topic_id}:{request.request_id}")
        prior_goal = await self._goals.repository.find_request(owner, str(request_id))
        if prior_goal is None and any(
            goal.status not in ("completed", "cancelled") for goal in goals
        ):
            raise ChatError("В теме уже есть задача. Отправьте уточнение к ней.")
        turn = await self._chats.send(owner, topic_id, request, workspace=True)
        if prior_goal is not None:
            return WorkspaceTurn(turn=turn, goal=prior_goal)
        if turn.status != "completed" or turn.next_action != "start_goal":
            return WorkspaceTurn(turn=turn)
        if len(request.message) < 10:
            return WorkspaceTurn(turn=turn)
        # Capture the handoff's bounded context, not messages arriving after it.
        history = await self._chats.repository.recent_conversation(
            owner, topic_id, before=turn.created_at
        )
        # A lost handoff response never causes a second model call or duplicate goal.
        goal = await self._goals.create(
            owner,
            topic_id,
            GoalCreate(
                request_id=request_id,
                objective=request.message,
                model_choice=request.model_choice,
                reasoning=request.reasoning,
                execution_mode="agent",
                constraints=(
                    "Ma’lumotlarni o‘zgartirmang va mijozlarga murojaat qilmang. "
                    "O‘zbek tilida (lotin yozuvida) javob bering."
                    if turn.response_language == "uz"
                    else "Не изменять данные и не связываться с клиентами."
                ),
                conversation_history=[
                    GoalConversationTurn(
                        user=item.message,
                        assistant=item.answer[:1000],
                        assistant_shortened=len(item.answer) > 1000,
                    )
                    for item in history.turns
                ],
                older_turns_omitted=history.older_turns_omitted,
                max_steps=self._goals.availability.max_steps,
                budget_microusd=self._goals.availability.budget_microusd,
            ),
            session_memory=turn.session_memory,
            capture_session_context=False,
        )
        return WorkspaceTurn(turn=turn, goal=goal)
