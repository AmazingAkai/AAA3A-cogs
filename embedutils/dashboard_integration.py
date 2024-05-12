from AAA3A_utils import CogsUtils  # isort:skip
from redbot.core import commands  # isort:skip
from redbot.core.bot import Red  # isort:skip
from redbot.core.i18n import Translator  # isort:skip
import discord  # isort:skip
import typing  # isort:skip

import os

from .converters import ListStringToEmbed

_ = Translator("EmbedUtils", __file__)

def dashboard_page(*args, **kwargs):
    def decorator(func: typing.Callable):
        func.__dashboard_decorator_params__ = (args, kwargs)
        return func
    return decorator


class DashboardIntegration:
    bot: Red

    @commands.Cog.listener()
    async def on_dashboard_cog_add(self, dashboard_cog: commands.Cog) -> None:
        dashboard_cog.rpc.third_parties_handler.add_third_party(self)

    # @dashboard_page(name=None, description="Create Embeds!")
    # async def global_callback(self, **kwargs) -> None:
    #     return {"status": 0, "web_content": {"source": '<iframe class="..." src="{{ url_for("third_parties_blueprint.third_party", name=name, page="editor") }}" style="width: 100%; height: 1000px; border: none;"></iframe>', "fullscreen": True}}

    @dashboard_page(name=None, description="Create rich Embeds!")
    async def dashboard_editor(self, **kwargs) -> None:
        file_path = os.path.join(os.path.dirname(__file__), "editor.html")
        with open(file_path, "rt") as f:
            source = f.read()
        return {"status": 0, "web_content": {"source": source, "standalone": True}}

    @dashboard_page(name="guild", description="Create rich Embeds and send them to a guild!", methods=["GET", "POST"])
    async def dashboard_guild(self, user: discord.User, guild: discord.Guild, **kwargs) -> None:
        is_owner = user.id in self.bot.owner_ids
        member = guild.get_member(user.id)
        if not is_owner and not await self.bot.is_mod(member):
            return {
                "status": 0,
                "error_code": 403,
                "message": _("You don't have permissions to access this page."),
            }
        text_channels = []
        voice_channels = []
        categorized_channels = {}
        for channel in sorted(guild.channels, key=lambda channel: channel.position):
            if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                continue
            bot_permissions = channel.permissions_for(guild.me)
            if (
                not bot_permissions.send_messages
                or not bot_permissions.embed_links
            ):
                continue
            if not is_owner:
                permissions = channel.permissions_for(member)
                if not permissions.send_messages or not permissions.embed_links:
                    continue
            channel_payload = {"id": str(channel.id), "name": channel.name, "type": channel.type, "position": channel.position}
            if channel.category is not None:
                categorized_channels.setdefault(channel.category, []).append(channel_payload)
            elif isinstance(channel, discord.TextChannel):
                text_channels.append(channel_payload)
            else:
                voice_channels.append(channel_payload)
        channels = text_channels + voice_channels
        for category in sorted(categorized_channels.items(), key=lambda category: category[0].position):
            channels.extend(
                sorted(
                    category[1],
                    key=lambda channel: (
                        1 if channel["type"] == discord.ChannelType.voice else 0,
                        channel["position"],
                    ),
                )
            )
        if not channels:
            return {
                "status": 0,
                "error_code": 403,
                "message": _("I or you don't have permissions to send messages or embeds in any channel in this guild."),
            }

        file_path = os.path.join(os.path.dirname(__file__), "editor.html")
        with open(file_path, "rt") as f:
            source = f.read()

        import wtforms
        class SendForm(kwargs["Form"]):
            def __init__(self) -> None:
                super().__init__(prefix="send_form_")

            username: wtforms.HiddenField = wtforms.HiddenField(_("Username:"), validators=[wtforms.validators.Optional(), wtforms.validators.Length(max=80)])
            avatar: wtforms.HiddenField = wtforms.HiddenField(_("Avatar URL:"), validators=[wtforms.validators.Optional(), wtforms.validators.URL()])
            data: wtforms.HiddenField = wtforms.HiddenField(_("Data"), validators=[wtforms.validators.DataRequired(), kwargs["DpyObjectConverter"](ListStringToEmbed)])
            channels: wtforms.SelectMultipleField = wtforms.SelectMultipleField(_("Channels:"), choices=[], validators=[wtforms.validators.DataRequired(), kwargs["DpyObjectConverter"](typing.Union[discord.TextChannel, discord.VoiceChannel])])
            submit = wtforms.SubmitField(_("Send Message(s)"))
        send_form: SendForm = SendForm()
        send_form.channels.choices = [(str(channel["id"]), channel["name"]) for channel in channels]
        send_form_string = f"""
            <form action="" method="POST" role="form" enctype="multipart/form-data">
                {send_form.hidden_tag()}
                {send_form.channels() }
                {send_form.submit(onclick='this.parentElement.querySelector("#send_form_username").value = document.querySelector(".editSenderUsername").value; this.parentElement.querySelector("#send_form_avatar").value = document.querySelector(".editSenderAvatar").value; this.parentElement.querySelector("#send_form_data").value = (JSON.stringify(typeof jsonCode === "object" ? jsonCode : json));', style="cursor: pointer; margin-left: 105px;") }
            </form>
        """

        if send_form.validate_on_submit() and await send_form.validate_dpy_converters():
            notifications = []
            for channel in send_form.channels.data:
                if send_form.username.data or send_form.avatar.data:
                    if not channel.permissions_for(guild.me).manage_webhooks:
                        notifications.append(
                            {
                                "message": f"{channel.name} ({channel.id}): I don't have permissions to manage webhooks in this channel.",
                                "category": "danger",
                            }
                        )
                        continue
                    if not is_owner and not channel.permissions_for(member).manage_webhooks:
                        notifications.append(
                            {
                                "message": f"{channel.name} ({channel.id}): You don't have permissions to manage webhooks in this channel.",
                                "category": "danger",
                            }
                        )
                        continue
                    try:
                        hook: discord.Webhook = await CogsUtils.get_hook(bot=self.bot, channel=channel)
                        await hook.send(
                            **send_form.data.data,
                            username=send_form.username.data or guild.me.display_name,
                            avatar_url=send_form.avatar.data or guild.me.display_avatar,
                            wait=True,
                        )
                    except discord.HTTPException as error:
                        notifications.append(
                            {
                                "message": f"{channel.name} ({channel.id}): {str(error)}",
                                "category": "danger",
                            }
                        )
                else:
                    try:
                        await channel.send(**send_form.data.data)
                    except Exception as e:
                        notifications.append(
                            {
                                "message": f"{channel.name} ({channel.id}): {str(e)}",
                                "category": "danger",
                            }
                        )
            if not notifications:
                self.logger.trace(f"{len(send_form.channels.data)} message(s) sent successfully in `{channel.name}` ({channel.id}) in `{guild.name}` ({guild.id}), from the Dashboard by `{user.display_name}` ({user.id}).")
                notifications.append({"message": _("Message(s) sent successfully!"), "category": "success"})
            return {"status": 0, "notifications": notifications, "redirect_url": kwargs["request_url"]}

        return {
            "status": 0,
            "web_content": {"source": source, "standalone": True, "send_form": send_form_string},
        }