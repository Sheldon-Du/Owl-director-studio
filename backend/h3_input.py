"""Five-source H3 model contract; full production state stays in program memory."""
import copy,re
from . import shot_references

SYSTEM='''You write approved storyboards directly as CHINESE H3 film directions; do not create an English draft first. The input has exactly five sources: creative_storyboards, finalized_storyboards, h3_format, subject_definitions and media_references.
Use BOTH storyboard sources. Creative text supplies narrative and visual intent; final text alone controls action/camera timing, performance, screen direction and opening/closing states. Do not add events or alter identity, causality, dialogue or duration. Write composition once per shot and changes once per action; stable appearance and light persist. Parallel tracks remain parallel.
The program owns reference labels, shot/action IDs, cuts, timestamps and exact dialogue. Return only the JSON output_template, in its supplied order, with every source_id/action key unchanged. Never output timestamps, <d> dialogue or extra speaking lines in descriptions. Dialogue in the final source is context only. Off-screen narration never drives visible lips; overlapping scheduled speakers are permitted.
Write descriptions, summaries, camera, sound and continuity directly in simplified Chinese. Use the supplied Subject labels for character identity. Keep JSON keys, reference labels and required relation enums in their original format. Visible scene text remains exact in double quotes. Only use labels allowed in the current shot. RefMod video locks character identity, not its motion or montage. Frame references constrain their listed shot/stage, not other shots; never apply a later object state early. Same-identity variants are one entity, not duplicates. Media background, whiteboards and grids are not scene content. Do not claim to have viewed an image.
Follow h3_format for this mode. From the FIRST draft, keep the FINAL ASSEMBLED prompt within 6000 characters, including program-owned dialogue, timing, reference rules and syntax. Follow character_budget field allocations as maximums, not minimums. Preserve all events and actions using terse clauses; establish appearance, light and framing once. Produce concise, usable directions on this first call. Code retains the original and all edit history; if over budget, correct the existing Chinese draft using concise Chinese; do not translate to English. Aim for 5200 assembled characters and never exceed 6000. Use short clauses, minimal metadata and action changes only; never pad toward the budget. Avoid repetition and rule explanations. Previous/next handoff and enabled camera/art guidance only refine the approved content. JSON only, no Markdown or reasoning.'''

def mode_rules(mode):
    common={'mode':mode,'final_limit_characters':6000,'output_language':'zh','program_owned':['exact dialogue and language tags','speaker IDs','shot numbers and cut times','action times','reference labels'],'sound':'Physical ambience/foley only when approved; no invented voices. Only final_mixed_audio preserves silences/speed. voice_timbre supplies timbre/accent only: generate new speech and synchronized lips, never copy sample words, timing or background.','music':'N/A unless explicitly approved in the final storyboard.'}
    if mode=='Ref2VA':
        common.update(section_order=['subject_definitions','summary','retention_analysis','detailed_description','overall_soundscape','non_diegetic_music'],reference_rules='Define each Subject and source Picture/Video label once; summary states the task; retention_analysis states fully_preserved, partially_preserved, attribute_transfer or weak_reference for each actual reference. Pictures are target-frame/composition anchors; RefMod videos provide identity only; Audio role is explicit: voice_timbre guides newly generated speech only; final_mixed_audio preserves the soundtrack. detailed_description follows playback order.')
    else:common.update(section_order=['integrated_multimodal_description','overall_soundscape','non_diegetic_music'],frame_alignment={'T2VA':'No frame alignment instruction.','I2VA':'Program fixes Picture 1 at the first frame.','FL2VA':'Program fixes Picture 1 at start and Picture 2 at the final frame.','L2VA':'Program fixes Picture 1 at the final frame.'}.get(mode,''))
    return common

def appearance(subject,cards):
    card=cards.get(subject.get('asset_id'),{})
    if card.get('subject'):return card['subject']
    text=str(subject.get('description',''))
    match=re.search(r'(?:^|\n)Subject 主体[：:]\s*(.*?)(?=\n[^\n]{1,40}[：:]|$)',text,re.S)
    return match[1].strip() if match else text

def build(step,request,template,mode,refs,subjects,payload):
    creative=[];final=[];wire_by_native={native['source_id']:wire['source_id'] for native,wire in zip(step['clips'],request['clips'])}
    for native,wire in zip(step['clips'],request['clips']):
        identity=wire['source_id'];row={'source_id':identity,'prompt':native.get('creative_storyboard_prompt') or native.get('description','')}
        # Already gated by enabled professional mode in h3.groups.
        if native.get('camera_override'):row['enabled_camera_guidance']=copy.deepcopy(native['camera_override'])
        if native.get('shot_examples'):row['shot_examples']=native['shot_examples']
        if native.get('native_prompt'):row['enabled_professional_prompt']=native['native_prompt']
        creative.append(row)
        timing={'source_id':identity,'start':native['start'],'end':native['end'],'prompt':native.get('finalized_storyboard_prompt'),'render_slots':[{'key':w['key'],'start':a['start'],'end':a['end'],**({'continuation':True,'source_offset':a.get('source_action_offset',0)} if a.get('continuation') else {})} for a,w in zip(native['actions'],wire['actions'])]}
        if not timing['prompt']:
            timing['approved_legacy_actions']=[{k:a.get(k) for k in ('description','dialogue','voiceover') if a.get(k)} for a in native['actions']]
        final.append(timing)
    final_source={'shots':final}
    if step.get('speaker_bindings'):final_source['speakers']=[{k:r.get(k) for k in ('speaker','speaker_id','subject_label')} for r in step['speaker_bindings']]
    if payload.get('previous_handoff'):final_source['previous_handoff']=payload['previous_handoff']
    if payload.get('next_source'):final_source['next_shot_intent']=payload['next_source'].get('description','')
    definitions=[]
    for subject in subjects:
        allowed=[wire_by_native[c['source_id']] for c in step['clips'] if set(subject.get('asset_ids') or [subject.get('asset_id')]).intersection(c.get('asset_ids',[]))]
        row={'label':subject['label'],'name':subject.get('name',''),'key_appearance':appearance(subject,payload.get('_asset_cards',{})),'media_labels':subject.get('pictures',[]),'allowed_shots':list(dict.fromkeys(allowed))}
        changes=[{'media':state['picture'],'stage':state.get('stage'),'state_change':state['change']} for state in subject.get('states',[]) if state.get('change')]
        if changes:row['state_variants']=list({str(c):c for c in changes}.values())
        definitions.append(row)
    media=[]
    for ref in refs:
        allowed=set();frames=[];usages=[]
        for index,clip in enumerate(step['clips'],1):
            if index in ref.get('asset_shots',[]) or any(b.get('asset_id') in clip.get('asset_ids',[]) for b in ref.get('bindings',[])):allowed.add(wire_by_native[clip['source_id']])
        for binding in ref.get('frame_bindings',[]):
            identity=wire_by_native.get(binding['source_id'])
            if not identity:continue
            allowed.add(identity);frame={'shot':identity,'role':binding['role']}
            if 'at' in binding:frame['at']=binding['at']
            else:frame.update(start=binding['start'],end=binding['end'])
            # Only an intermediate frame may add a state not described by final endpoints.
            if binding['role']=='keyframe' and binding.get('description',{}).get('subject'):frame['key_state']=binding['description']['subject']
            frames.append(frame)
        for binding in ref.get('bindings',[]):
            use={k:binding[k] for k in ('stage','role','usage','state') if binding.get(k)}
            if use and use not in usages:usages.append(use)
        media.append({'label':ref['label'],'kind':'character_refmod' if ref.get('refmod') else ref.get('media_type','image'),'allowed_shots':sorted(allowed) if allowed else list(wire_by_native.values()),**({'frames':frames} if frames else {}),**({'asset_usage':usages} if usages else {}),**({'role':ref['role']} if ref.get('role') else {}),**({'speaker':ref['speaker'],'subject_label':ref.get('subject_label')} if ref.get('speaker') else {})})
    if step.get('audio_binding'):media.append({'label':'<Audio 1>','kind':'final_mixed_audio','duration':step['duration'],'preserve':'voices, exact words, timing, speed, overlaps and all silence','allowed_shots':list(wire_by_native.values())})
    from . import h3
    rules=mode_rules(mode);rules['output_template']=template
    if any(row.get('shot_examples') for row in creative):rules['shot_examples_rule']=shot_references.RULE
    rules['character_budget']=h3.rewrite_budget(step,mode,refs,subjects)
    if payload.get('applied_art_style'):rules['applied_art_style']=payload['applied_art_style']
    return {'creative_storyboards':creative,'finalized_storyboards':final_source,'h3_format':rules,'subject_definitions':definitions,'media_references':media}
