from app.services.status_codes import RabStatus, is_pending, is_sdl_requested, KNOWN_STATUSES, from_record

print('RabStatus.SDL_REQUESTED:', RabStatus.SDL_REQUESTED)
print('is_pending(None):', is_pending(None))
print('is_sdl_requested("sdl_requested"):', is_sdl_requested('sdl_requested'))
print('KNOWN_STATUSES:', KNOWN_STATUSES)
print('from_record("sdl_requested"):', from_record('sdl_requested'))
print('from_record("unknown"):', from_record('unknown'))