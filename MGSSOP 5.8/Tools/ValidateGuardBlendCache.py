"""Validate saved blend segments and run actual guard animation updates.

Run with UnrealEditor-Cmd <project> /Engine/Maps/Entry
-ExecutePythonScript=<this file> -nullrhi -unattended -NoSaveConfig.
The frame test uses an isolated, unsaved world and never saves gameplay assets.
"""
import json
import math
import os
import re
import time
import traceback
import unreal

ROOT = '/Game/Actors/Characters/Enemy/Guard/'
FOLDER = os.path.join(unreal.Paths.project_saved_dir(), 'Codex', 'GuardLocomotion')
REPORT = os.path.join(FOLDER, 'blend-cache-validation.json')


def validate_cache(blend):
    """Read serialized, protected runtime data through Unreal's text exporter."""
    os.makedirs(FOLDER, exist_ok=True)
    exported = os.path.abspath(os.path.join(FOLDER, 'BS_GuardLocomotion-validated.copy'))
    task = unreal.AssetExportTask()
    task.set_editor_property('Object', blend)
    task.set_editor_property('Filename', exported)
    task.set_editor_property('bAutomated', True)
    task.set_editor_property('bPrompt', False)
    task.set_editor_property('bReplaceIdentical', True)
    task.set_editor_property('Exporter', unreal.ObjectExporterT3D())
    assert unreal.Exporter.run_asset_export_task(task), 'Cannot export the runtime blend cache'
    with open(exported, encoding='utf-8-sig') as handle:
        text = handle.read()
    cache = next(line for line in text.splitlines() if 'BlendSpaceData=' in line)
    pairs = [(int(a), int(b)) for a, b in re.findall(
        r'SampleIndices\[0\]=(-?\d+),SampleIndices\[1\]=(-?\d+)', cache)]
    assert pairs == [(0, 1), (1, 2)], ('Invalid runtime segments', cache)
    count = len(blend.get_editor_property('SampleData'))
    assert count == 3 and all(0 <= index < count for pair in pairs for index in pair)
    # The shared boundary must match Walk_Guard at 150 on a 0..350 speed axis.
    boundaries = [float(value) for value in re.findall(r'Vertices\[\d+\]=([\d.eE+-]+)', cache)]
    assert any(math.isclose(value, 150.0 / 350.0, abs_tol=0.000001) for value in boundaries), cache
    assert not any(math.isclose(value, 250.0 / 350.0, abs_tol=0.000001) for value in boundaries), cache
    return {'segments': pairs, 'sampleCount': count, 'export': exported}


def run_frame_test():
    report = {'passed': False, 'frames': 0, 'shotsFired': 0, 'runningShots': 0,
              'fireAttempts': [], 'shotsByWeapon': {}, 'speeds': []}
    os.makedirs(FOLDER, exist_ok=True)
    with open(REPORT, 'w', encoding='utf-8') as handle:
        json.dump(report, handle)
    fixture = {'actors': [], 'callback': None, 'poses': set()}
    started = time.monotonic()
    speeds = [0, 40, 100, 149, 150, 151, 200, 249, 250, 251, 300, 349, 350, 400, 350, 250, 150, 0]
    frames_per_speed = 36

    def invoke(obj, method, *args):
        return obj.call_method(method, args=args)

    def finish(error=None):
        if fixture['callback'] is not None:
            unreal.unregister_slate_post_tick_callback(fixture['callback'])
            fixture['callback'] = None
        if error:
            report['error'] = error
            unreal.log_error(error)
        report['distinctPoses'] = len(fixture['poses'])
        report['elapsedSeconds'] = round(time.monotonic() - started, 2)
        for actor in reversed(fixture['actors']):
            if unreal.SystemLibrary.is_valid(actor):
                actor.destroy_actor()
        if unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_end_play()
        with open(REPORT, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, indent=2)
        unreal.EditorPythonScripting.set_keep_python_script_alive(False)

    try:
        blend = unreal.load_asset(ROOT + 'Animation/BS_GuardLocomotion')
        report['cache'] = validate_cache(blend)
        unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
        editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        level_editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        settings = unreal.GameplayStatics.get_all_actors_of_class(editor.get_editor_world(), unreal.WorldSettings)[0]
        settings.set_editor_property('DefaultGameMode', unreal.GameModeBase.static_class())
        aim = unreal.Vector(2000, 0, 2000)

        def setup_game_fixture(world):
            guard_class = unreal.load_class(None, ROOT + 'BP_EnemyBase_Child.BP_EnemyBase_Child_C')
            statics = unreal.get_default_object(unreal.GameplayStatics)
            transform = unreal.Transform(location=unreal.Vector(0, 0, 2000))
            guard = invoke(statics, 'BeginDeferredActorSpawnFromClass', world, guard_class, transform,
                           unreal.SpawnActorCollisionHandlingMethod.ALWAYS_SPAWN, None,
                           unreal.SpawnActorScaleMethod.MULTIPLY_WITH_ROOT)
            guard.set_editor_property('AutoPossessAI', unreal.AutoPossessAI.DISABLED)
            guard = invoke(statics, 'FinishSpawningActor', guard, transform,
                           unreal.SpawnActorScaleMethod.MULTIPLY_WITH_ROOT)
            fixture['actors'].append(guard)
            guard.set_actor_enable_collision(False)
            mesh = guard.get_editor_property('Mesh')
            movement = guard.get_editor_property('CharacterMovement')
            # Keep controlled velocities while the game world evaluates the real AnimBP.
            movement.set_component_tick_enabled(False)
            mesh.set_editor_property('VisibilityBasedAnimTickOption',
                                     unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES)
            mesh.set_component_tick_enabled(True)
            equipment = guard.get_editor_property('BPC_Equipment')
            for old_weapon in equipment.get_editor_property('EquipedWeapon'):
                if unreal.SystemLibrary.is_valid(old_weapon):
                    old_weapon.destroy_actor()
            # Reproduce valid Mesh attachment locally; no gameplay Blueprint is changed.
            invoke(equipment, 'InitializeEquipement', mesh, unreal.Name('WeaponSocket'))
            weapons = list(equipment.get_editor_property('EquipedWeapon'))
            fixture['actors'].extend(weapons)
            invoke(equipment, 'SetForceInHand', True)
            assert len(weapons) == 2, 'Exercise both guard weapons with normal magazines'
            for weapon in weapons:
                invoke(weapon, 'InitAmmoFromData')
                assert weapon.get_editor_property('AmmoInMagazine') >= len(speeds), 'Insufficient test ammunition'
            fixture.update(guard=guard, mesh=mesh, movement=movement, equipment=equipment,
                           weapons=weapons, weapon=weapons[equipment.get_editor_property('CurrentWeaponIndex')])

        def tick(delta_seconds):
            try:
                assert time.monotonic() - started < 120, 'Animation frame test timed out'
                if 'guard' not in fixture:
                    world = editor.get_game_world()
                    if world and unreal.GameplayStatics.get_game_mode(world):
                        setup_game_fixture(world)
                    return
                mesh, movement = fixture['mesh'], fixture['movement']
                equipment, weapons = fixture['equipment'], fixture['weapons']
                frame = report['frames']
                stage, local_frame = divmod(frame, frames_per_speed)
                if stage >= len(speeds):
                    assert len(fixture['poses']) > 5, 'Skeletal poses did not advance'
                    assert len(report['fireAttempts']) == len(speeds) * 2, 'Missing firing requests'
                    assert report['shotsFired'] > 0, 'The fixture must exercise real weapon fire'
                    report['passed'] = True
                    finish()
                    return
                speed = speeds[stage]
                if stage == len(speeds) // 2 and local_frame == 0:
                    invoke(equipment, 'EquipWeapon', 1)
                    fixture['weapon'] = weapons[equipment.get_editor_property('CurrentWeaponIndex')]
                movement.set_editor_property('Velocity', unreal.Vector(speed, 0, 0))
                if local_frame >= 4:
                    instance = mesh.get_anim_instance()
                    assert instance and math.isclose(instance.get_editor_property('Speed'), speed, abs_tol=0.001), (
                        'The native animation update did not read actual guard velocity', speed)
                    pose = mesh.get_socket_transform('ORG-face', unreal.RelativeTransformSpace.RTS_COMPONENT)
                    position = pose.translation
                    assert all(math.isfinite(v) for v in [position.x, position.y, position.z])
                    fixture['poses'].add(tuple(round(v, 4) for v in [position.x, position.y, position.z]))
                if local_frame in [12, 30]:
                    weapon = fixture['weapon']
                    ammo_before = weapon.get_editor_property('AmmoInMagazine')
                    invoke(equipment, 'PrimaryActionCurrentWeapon', aim)
                    ammo_after = weapon.get_editor_property('AmmoInMagazine')
                    name = weapon.get_class().get_name()
                    report['fireAttempts'].append({'speed': speed, 'weapon': name,
                                                   'ammoBefore': ammo_before, 'ammoAfter': ammo_after})
                    # Weapon state can reject a request. This regression requires real
                    # shots and native pose evaluation throughout the crashing range;
                    # magazine/weapon-switch behavior is observed independently.
                    report['shotsByWeapon'].setdefault(name, 0)
                    if ammo_after == ammo_before - 1:
                        report['shotsFired'] += 1
                        report['shotsByWeapon'][name] += 1
                        if speed > 250:
                            report['runningShots'] += 1
                if local_frame == frames_per_speed - 1:
                    report['speeds'].append(speed)
                report['frames'] += 1
            except Exception:
                finish(traceback.format_exc())

        unreal.EditorPythonScripting.set_keep_python_script_alive(True)
        fixture['callback'] = unreal.register_slate_post_tick_callback(tick)
        level_editor.editor_play_simulate()
    except Exception:
        finish(traceback.format_exc())


if __name__ == '__main__':
    run_frame_test()
