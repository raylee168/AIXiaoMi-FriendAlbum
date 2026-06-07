if __package__:
    try:
        from .cowagent_plugin import MomentsAlbum  # noqa: F401
    except ModuleNotFoundError as exc:
        # CowAgent imports this package from plugins/moments_album. Local tests
        # and standalone FastAPI runs do not have CowAgent modules on sys.path.
        if exc.name not in {"plugins", "bridge", "common"}:
            raise
