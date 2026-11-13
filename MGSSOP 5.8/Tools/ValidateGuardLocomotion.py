"""Check guard animation wiring, AI speeds, and sleep/wake in an isolated editor.

Run with UnrealEditor-Cmd <project> -run=pythonscript -script=<this file>
-nullrhi -unattended. No map or gameplay asset is saved by these checks.
"""
import json
import os
import runpy
import traceback
import unreal

ROOT = '/Game/Actors/Characters/Enemy/'
GUARD = ROOT + 'Guard/BP_EnemyBase_Child'
ANIM = ROOT + 'Guard/Animation/ABP_GuardLocomotion'
REPORT = os.path.join(unreal.Paths.project_saved_dir(), 'Codex', 'GuardLocomotion', 'validation.json')
report = {'passed': False, 'checks': []}
actors = []


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    report['checks'].append(message)
    unreal.log('GUARD_LOCOMOTION_PASS: ' + message)


def invoke(obj, method, *args):
    return obj.call_method(method, args=args)


def run():
    blueprint = unreal.load_asset(GUARD)
    guard_class = unreal.load_class(None, GUARD + '.BP_EnemyBase_Child_C')
    anim_class = unreal.load_class(None, ANIM + '.ABP_GuardLocomotion_C')
    blend = unreal.load_asset(ROOT + 'Guard/Animation/BS_GuardLocomotion')
    check(all([blueprint, guard_class, anim_class, blend]), 'guard animation assets load')
    cache_check = runpy.run_path(os.path.join(unreal.Paths.project_dir(), 'Tools', 'ValidateGuardBlendCache.py'))
    cache_check['validate_cache'](blend)
    check(True, 'saved blend segments reference only the three current animation samples')
    defaults = unreal.get_default_object(guard_class)
    check(defaults.get_editor_property('Mesh').get_editor_property('AnimClass') == anim_class,
          'the saved guard mesh uses ABP_GuardLocomotion by default')
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    guard_class = unreal.load_class(None, GUARD + '.BP_EnemyBase_Child_C')
    check(unreal.get_default_object(guard_class).get_editor_property('Mesh').get_editor_property('AnimClass') == anim_class,
          'guard animation survives Blueprint recompilation')

    skeleton = blend.get_editor_property('Skeleton')
    samples = blend.get_editor_property('SampleData')
    actual = [(sample.get_editor_property('Animation').get_name(), sample.get_editor_property('SampleValue').x) for sample in samples]
    expected = [('Mesh_Base_A_Idle_Stealth', 0.0), ('Mesh_Base_A_Walk_Guard', 150.0), ('Mesh_Base_A_Run_Guard', 350.0)]
    check(actual == expected, 'idle, walk guard, and run guard match the 0/150/350 cm/s speed axis')
    check(all(sample.get_editor_property('Animation').get_editor_property('Skeleton') == skeleton for sample in samples),
          'all guard clips share the same skeleton')
    check(not any(sample.get_editor_property('Animation').get_editor_property('bEnableRootMotion') for sample in samples),
          'guard clips leave movement control to CharacterMovement')
    check(blend.get_editor_property('bLoop'), 'guard locomotion loops continuously')
    smoothing = blend.get_editor_property('InterpolationParam')[0].get_editor_property('InterpolationTime')
    check(0.0 < smoothing <= 0.3, 'walk/run changes use a short smooth transition')
    check(all(sample.get_editor_property('SampleValue').y == 0.0 and sample.get_editor_property('SampleValue').z == 0.0 for sample in samples),
          'guard locomotion samples use a single horizontal speed axis')

    tree = unreal.load_asset(ROOT + 'StateTree/ST_Enemy')
    data = unreal.StateTreeEditorData.get_editor_data(tree)
    pending = list(data.get_editor_property('SubTrees'))
    speeds = {}
    while pending:
        state = pending.pop()
        for task in state.get_editor_property('Tasks'):
            obj = task.get_editor_property('InstanceObject')
            if obj and obj.get_class().get_name().startswith('STT_MovementSpeed'):
                speeds[str(state.get_editor_property('Name'))] = obj.get_editor_property('MovementSpeed')
        pending.extend(state.get_editor_property('Children'))
    report['stateSpeeds'] = speeds
    check(speeds.get('Routine') == 150.0, 'patrol uses the guarded walk speed')
    check(speeds.get('RechercheLocale') == 250.0, 'search uses a speed between walking and running')
    check(speeds.get('Poursuite') == 350.0, 'pursuit uses the guarded run speed')
    check(max(speeds.values()) <= 350.0, 'the blend covers all configured AI movement speeds')

    # Check placed guards from the saved level, rather than only newly spawned guards.
    map_file = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir() + 'Maps/MapWorld.umap')
    world = unreal.EditorLoadingAndSavingUtils.load_map(map_file)
    placed = unreal.GameplayStatics.get_all_actors_of_class(world, guard_class)
    report['placedGuards'] = len(placed)
    check(len(placed) > 0, 'the saved level contains guards to validate')
    wrong = [actor.get_name() for actor in placed
             if actor.get_component_by_class(unreal.SkeletalMeshComponent).get_editor_property('AnimClass') != anim_class]
    check(not wrong, 'every placed guard inherits guard locomotion: ' + str(wrong))
    unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    guard = subsystem.spawn_actor_from_class(guard_class, unreal.Vector(0, 0, 100))
    actors.append(guard)
    controller_class = unreal.load_class(None, ROOT + 'BP_EnemyAIController.BP_EnemyAIController_C')
    statics = unreal.get_default_object(unreal.GameplayStatics)
    transform = unreal.Transform(location=unreal.Vector(0, 500, 100))
    controller = invoke(statics, 'BeginDeferredActorSpawnFromClass', guard, controller_class, transform,
                        unreal.SpawnActorCollisionHandlingMethod.ALWAYS_SPAWN, None,
                        unreal.SpawnActorScaleMethod.MULTIPLY_WITH_ROOT)
    controller = invoke(statics, 'FinishSpawningActor', controller, transform, unreal.SpawnActorScaleMethod.MULTIPLY_WITH_ROOT)
    actors.append(controller)
    controller.possess(guard)
    invoke(guard, 'InitializeEnemyActions', controller)
    mesh = guard.get_component_by_class(unreal.SkeletalMeshComponent)
    movement = guard.get_component_by_class(unreal.CharacterMovementComponent)
    anim = mesh.get_anim_instance()
    check(anim is not None and anim.get_class() == anim_class, 'a spawned guard initializes the guard animation instance')
    for label, speed, velocity in [
        ('patrol', 150.0, unreal.Vector(150, 0, 0)),
        ('search', 250.0, unreal.Vector(0, 250, 0)),
        ('pursuit', 350.0, unreal.Vector(210, 280, 0))]:
        invoke(guard, 'SetMovementSpeed', speed)
        check(abs(movement.get_editor_property('MaxWalkSpeed') - speed) < 0.001, label + ' applies its configured movement speed')
        movement.set_editor_property('Velocity', velocity)
        invoke(anim, 'BlueprintUpdateAnimation', 1.0 / 60.0)
        check(abs(anim.get_editor_property('Speed') - speed) < 0.001, label + ' animation reads actual horizontal velocity')
    movement.set_editor_property('Velocity', unreal.Vector(0, 0, 200))
    invoke(anim, 'BlueprintUpdateAnimation', 1.0 / 60.0)
    check(anim.get_editor_property('Speed') == 0.0, 'vertical motion does not incorrectly trigger running')
    movement.set_editor_property('Velocity', unreal.Vector())
    invoke(anim, 'BlueprintUpdateAnimation', 1.0 / 60.0)
    check(anim.get_editor_property('Speed') == 0.0, 'a stationary guard returns to idle')
    invoke(guard, 'EnterGuardSleep')
    check(mesh.get_editor_property('AnimationMode') == unreal.AnimationMode.ANIMATION_SINGLE_NODE,
          'sleep still uses its dedicated lying animation')
    invoke(guard, 'WakeGuard')
    anim = mesh.get_anim_instance()
    check(mesh.get_editor_property('AnimationMode') == unreal.AnimationMode.ANIMATION_BLUEPRINT,
          'waking restores animation blueprint mode')
    check(anim is not None and anim.get_class() == anim_class, 'waking restores guard locomotion')
    movement.set_editor_property('Velocity', unreal.Vector(150, 0, 0))
    invoke(anim, 'BlueprintUpdateAnimation', 1.0 / 60.0)
    check(anim.get_editor_property('Speed') == 150.0, 'guard walking resumes correctly after waking')
    for actor in reversed(actors):
        subsystem.destroy_actor(actor)
    actors.clear()

    runpy.run_path(os.path.join(unreal.Paths.project_dir(), 'Tools', 'ValidateTranquilizers.py'))
    with open(os.path.join(unreal.Paths.project_saved_dir(), 'Codex', 'tranquilizers-validation.json'), encoding='utf-8') as stream:
        regression = json.load(stream)
    check(regression['passed'], 'the head/body tranquilizer and wake regression suite still passes')
    report['tranquilizerChecks'] = len(regression['checks'])


try:
    run()
    report['passed'] = True
except Exception:
    report['error'] = traceback.format_exc()
    unreal.log_error(report['error'])
finally:
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in reversed(actors):
        if unreal.SystemLibrary.is_valid(actor):
            subsystem.destroy_actor(actor)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, 'w', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    unreal.log('GUARD_LOCOMOTION_VALIDATION: ' + json.dumps(report))
if not report['passed']:
    raise AssertionError('Guard locomotion validation failed; see ' + REPORT)
