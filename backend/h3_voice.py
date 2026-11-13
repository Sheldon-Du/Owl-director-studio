"""Voice samples condition newly generated speech; never drive fixed audio."""
import shutil
from . import store, speech_audio, timing_speech


def locked(shot):
    return shot.get('h3_audio_mode') == 'locked'


def references(project, step, subjects, prepare=False):
    refs = []
    for clip in step['clips']:
        shot = next(s for s in project['shots'] if s['id'] == clip['source_id'])
        if locked(shot):
            continue
        for line in timing_speech.raw_catalogue(project, shot):
            speaker = speech_audio.role(line)
            if any(r['speaker'] == speaker for r in refs):
                continue
            asset = next((a for a in project.get('assets', []) if a.get('kind') == 'character' and a.get('name') == speaker), {})
            config = project.get('tts_voice_roles', {}).get(speaker, {})
            external_path = None
            media = asset.get('voice', {}).get('reference_media') or config.get('voice_ref_media')
            filename = config.get('voice_filename', '') or ''
            if not media and filename.startswith('owl:'):
                from . import yovoice_cli
                media = next((r.get('media') for r in yovoice_cli.own_voices() if r['filename'] == filename), None)
            if not media and filename.startswith('cli:'):
                from . import yovoice_cli
                path = yovoice_cli.DATA / 'voices' / (filename[4:] + '.wav')
                if path.is_file():
                    media = 'h3-voice-' + filename[4:] + '.wav'
                    external_path = path
                    if prepare and not store.media_path(media).is_file():
                        shutil.copy2(path, store.media_path(media))
            if not media:
                measured = speech_audio.measurement(project, shot, line)
                media = measured.get('media') if measured else None
            if not media or not (store.media_path(media).is_file() or external_path and external_path.is_file()):
                raise ValueError('角色“' + speaker + '”缺少可用声音参考，请绑定角色参考音频或生成一句声音样本')
            refs.append({'label': f'<Audio {len(refs)+1}>', 'media': media,
                         'media_type': 'audio', 'role': 'voice_timbre', 'speaker': speaker,
                         'subject_label': next((s['label'] for s in subjects if s.get('name') == speaker), None)})
    return refs


def instructions(refs):
    return '\n'.join(
        f'{r["label"]} provides only voice timbre/accent for {r.get("subject_label") or r["speaker"]}. '
        'Generate the scripted words anew with synchronized mouth motion and natural pauses. '
        'Do not copy the sample words, soundtrack timing or background sounds.'
        for r in refs if r.get('role') == 'voice_timbre')
