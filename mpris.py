import threading
from typing import Callable, Optional

MPRIS_IFACE = "org.mpris.MediaPlayer2"
MPRIS_PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
DBUS_PATH = "/org/mpris/MediaPlayer2"
BUS_NAME = "org.mpris.MediaPlayer2.ytdl"


class MprisPlayer:
    """MPRIS2 D-Bus service for Bluetooth/media-key control."""

    def __init__(
        self,
        on_next: Callable,
        on_previous: Callable,
        on_play_pause: Callable,
        on_play: Callable,
        on_pause: Callable,
    ):
        import dbus
        import dbus.service
        import dbus.mainloop.glib
        from gi.repository import GLib

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()
        bus_name = dbus.service.BusName(BUS_NAME, bus)
        self._obj = _MprisObject(bus_name, on_next, on_previous, on_play_pause, on_play, on_pause)
        self._loop = GLib.MainLoop()
        threading.Thread(target=self._loop.run, daemon=True).start()

    def update(self, title: str, status: str):
        self._obj.update(title, status)

    def stop(self):
        self._loop.quit()


class _MprisObject:
    """Inner dbus.service.Object — kept separate so MprisPlayer can be imported without dbus."""

    def __init__(self, bus_name, on_next, on_previous, on_play_pause, on_play, on_pause):
        import dbus
        import dbus.service

        self._dbus = dbus
        self._title = ""
        self._status = "Stopped"

        # Build the service object dynamically so we can keep dbus import lazy.
        on_next_ = on_next
        on_prev_ = on_previous
        on_pp_ = on_play_pause
        on_play_ = on_play
        on_pause_ = on_pause
        outer = self

        class _Obj(dbus.service.Object):
            @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ss", out_signature="v")
            def Get(self, iface, prop):
                return self.GetAll(iface)[prop]

            @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
            def GetAll(self, iface):
                d = outer._dbus
                if iface == MPRIS_IFACE:
                    return {
                        "CanQuit": d.Boolean(False),
                        "CanRaise": d.Boolean(False),
                        "HasTrackList": d.Boolean(False),
                        "Identity": d.String("ytdl player"),
                        "SupportedUriSchemes": d.Array([], signature="s"),
                        "SupportedMimeTypes": d.Array([], signature="s"),
                    }
                if iface == MPRIS_PLAYER_IFACE:
                    return {
                        "PlaybackStatus": d.String(outer._status),
                        "LoopStatus": d.String("None"),
                        "Rate": d.Double(1.0),
                        "Shuffle": d.Boolean(False),
                        "Metadata": outer._metadata(),
                        "Volume": d.Double(1.0),
                        "Position": d.Int64(0),
                        "MinimumRate": d.Double(1.0),
                        "MaximumRate": d.Double(1.0),
                        "CanGoNext": d.Boolean(True),
                        "CanGoPrevious": d.Boolean(True),
                        "CanPlay": d.Boolean(True),
                        "CanPause": d.Boolean(True),
                        "CanSeek": d.Boolean(False),
                        "CanControl": d.Boolean(True),
                    }
                raise d.exceptions.DBusException(f"Unknown interface: {iface}")

            @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ssv")
            def Set(self, iface, prop, value):
                pass

            @dbus.service.signal(dbus.PROPERTIES_IFACE, signature="sa{sv}as")
            def PropertiesChanged(self, iface, changed, invalidated):
                pass

            @dbus.service.method(MPRIS_IFACE)
            def Raise(self): pass

            @dbus.service.method(MPRIS_IFACE)
            def Quit(self): pass

            @dbus.service.method(MPRIS_PLAYER_IFACE)
            def Next(self): on_next_()

            @dbus.service.method(MPRIS_PLAYER_IFACE)
            def Previous(self): on_prev_()

            @dbus.service.method(MPRIS_PLAYER_IFACE)
            def Pause(self): on_pause_()

            @dbus.service.method(MPRIS_PLAYER_IFACE)
            def PlayPause(self): on_pp_()

            @dbus.service.method(MPRIS_PLAYER_IFACE)
            def Stop(self): on_pause_()

            @dbus.service.method(MPRIS_PLAYER_IFACE)
            def Play(self): on_play_()

            @dbus.service.method(MPRIS_PLAYER_IFACE, in_signature="x")
            def Seek(self, offset): pass

            @dbus.service.method(MPRIS_PLAYER_IFACE, in_signature="ox")
            def SetPosition(self, track_id, position): pass

            @dbus.service.method(MPRIS_PLAYER_IFACE, in_signature="s")
            def OpenUri(self, uri): pass

            @dbus.service.signal(MPRIS_PLAYER_IFACE, signature="x")
            def Seeked(self, position): pass

        self._svc = _Obj(bus_name, DBUS_PATH)

    def _metadata(self):
        d = self._dbus
        return d.Dictionary(
            {
                "mpris:trackid": d.ObjectPath("/org/mpris/MediaPlayer2/TrackList/NoTrack"),
                "xesam:title": d.String(self._title),
            },
            signature="sv",
        )

    def update(self, title: str, status: str):
        self._title = title
        self._status = status
        try:
            self._svc.PropertiesChanged(
                MPRIS_PLAYER_IFACE,
                {
                    "PlaybackStatus": self._dbus.String(status),
                    "Metadata": self._metadata(),
                },
                [],
            )
        except Exception:
            pass


def start_mpris(
    on_next: Callable,
    on_previous: Callable,
    on_play_pause: Callable,
    on_play: Callable,
    on_pause: Callable,
) -> Optional[MprisPlayer]:
    try:
        return MprisPlayer(on_next, on_previous, on_play_pause, on_play, on_pause)
    except Exception as e:
        print(f"[MPRIS2] Failed to start (media keys unavailable): {e}")
        return None
