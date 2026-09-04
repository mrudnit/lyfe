"""Spending LYFE POINTS.

Only rewards that somebody can actually deliver appear here. For now that is a
guaranteed play, which needs nobody at all; door rewards exist in the database
but stay switched off until there is a person at the entrance free to hand them
over.
"""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.bot.keyboards import button_texts, main_menu
from lyfe.core.services import event_service, reward_service, user_service
from lyfe.core.services.reward_service import BuyResult
from lyfe.i18n import t
from lyfe.models import Reward, RewardKind, User

logger = logging.getLogger(__name__)
router = Router(name="rewards")


@router.message(F.text.in_(button_texts("btn_rewards")))
async def show_rewards(message: Message, user: User, session: AsyncSession):
    lang = user.language
    event = await event_service.get_next_event(session)
    if event is None:
        await message.answer(t("rewards_no_event", lang), reply_markup=main_menu(lang))
        return

    balance = await user_service.get_points_balance(session, user.id)
    rewards = await reward_service.available_rewards(session, event=event)
    held = await reward_service.held_by_user(session, user_id=user.id, event_id=event.id)

    if not rewards:
        await message.answer(t("rewards_empty", lang, points=balance), reply_markup=main_menu(lang))
        return

    lines = [t("rewards_header", lang, points=balance), ""]
    buttons = []
    for reward in rewards:
        affordable = balance >= reward.cost_points
        lines.append(f"{'▸' if affordable else '·'} {reward.name} — {reward.cost_points}")
        if reward.description:
            lines.append(f"   {reward.description}")
        if affordable:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"{reward.name} · {reward.cost_points}",
                        callback_data=f"rw:buy:{reward.id}",
                    )
                ]
            )

    if held:
        lines.append("")
        lines.append(t("rewards_held", lang))
        for redemption in held:
            lines.append(f"· {redemption.reward.name} — {redemption.code}")

    await message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None,
    )


@router.callback_query(F.data.startswith("rw:buy:"))
async def buy(callback: CallbackQuery, user: User, session: AsyncSession):
    lang = user.language
    reward = await session.get(Reward, int(callback.data.split(":")[2]))
    event = await event_service.get_next_event(session)
    if reward is None or event is None:
        await callback.answer(t("error", lang))
        return

    # A guaranteed play needs to know which track, so ask first.
    if reward.kind == RewardKind.PRIORITY_TRACK:
        tracks = await reward_service.user_requests_for_event(
            session, user_id=user.id, event_id=event.id
        )
        if not tracks:
            await callback.answer(t("priority_no_tracks", lang), show_alert=True)
            return

        buttons = [
            [
                InlineKeyboardButton(
                    text=event_track.track.display[:60],
                    callback_data=f"rw:pri:{reward.id}:{event_track.id}",
                )
            ]
            for event_track in tracks
        ]
        await callback.answer()
        await callback.message.answer(
            t("priority_pick", lang, cost=reward.cost_points),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
        return

    outcome = await reward_service.purchase(session, user=user, reward=reward, event=event)
    await callback.answer()
    await _report(callback.message, user, reward, outcome)


@router.callback_query(F.data.startswith("rw:pri:"))
async def buy_priority(callback: CallbackQuery, user: User, session: AsyncSession):
    lang = user.language
    _, _, reward_id, event_track_id = callback.data.split(":")

    reward = await session.get(Reward, int(reward_id))
    event = await event_service.get_next_event(session)
    if reward is None or event is None:
        await callback.answer(t("error", lang))
        return

    outcome = await reward_service.purchase(
        session,
        user=user,
        reward=reward,
        event=event,
        payload={"event_track_id": int(event_track_id)},
    )
    await callback.answer()
    await _report(callback.message, user, reward, outcome)


async def _report(message: Message, user: User, reward: Reward, outcome) -> None:
    lang = user.language

    if outcome.status == BuyResult.OK:
        if reward.kind == RewardKind.PRIORITY_TRACK:
            text = t("priority_done", lang, points=outcome.balance)
        else:
            text = t(
                "reward_bought",
                lang,
                name=reward.name,
                code=outcome.redemption.code,
                points=outcome.balance,
            )
        await message.answer(text, reply_markup=main_menu(lang))
        return

    messages = {
        BuyResult.NOT_ENOUGH_POINTS: t(
            "reward_not_enough", lang, need=reward.cost_points, have=outcome.balance
        ),
        BuyResult.SOLD_OUT: t("reward_sold_out", lang),
        BuyResult.LIMIT_REACHED: t("reward_limit", lang),
        BuyResult.UNAVAILABLE: t("reward_unavailable", lang),
        BuyResult.NO_TRACK: t("priority_no_tracks", lang),
        BuyResult.PRIORITY_FULL: t("priority_full", lang),
    }
    await message.answer(messages.get(outcome.status, t("error", lang)), reply_markup=main_menu(lang))
