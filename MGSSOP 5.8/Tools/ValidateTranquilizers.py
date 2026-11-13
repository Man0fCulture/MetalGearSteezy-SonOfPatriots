"""Validate saved tranquilizer head/body routing in an isolated Unreal world.

Run with UnrealEditor-Cmd <project> -run=pythonscript -script=<this file>
-nullrhi -unattended. No gameplay asset or map is saved by this test.
The JSON report is written to Saved/Codex/tranquilizers-validation.json.
"""
import json
import os
import traceback
import unreal

REPORT = os.path.join(unreal.Paths.project_saved_dir(), 'Codex', 'tranquilizers-validation.json')
report = {'passed': False, 'checks': []}
actors = []


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    report['checks'].append(message)
    unreal.log('TRANQUILIZER_PASS: ' + message)


def invoke(obj, method, *args):
    return obj.call_method(method, args=args)


def run():
    unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    guard_class = unreal.load_class(None, '/Game/Actors/Characters/Enemy/Guard/BP_EnemyBase_Child.BP_EnemyBase_Child_C')
    controller_class = unreal.load_class(None, '/Game/Actors/Characters/Enemy/BP_EnemyAIController.BP_EnemyAIController_C')
    stats_class = unreal.load_class(None, '/Game/Components/Stats/BPC_Stats.BPC_Stats_C')
    tranquilizer = unreal.load_class(None, '/Game/DamageType/DT_NonLethal.DT_NonLethal_C')
    lethal = unreal.load_class(None, '/Game/DamageType/DT_Lethal.DT_Lethal_C')
    check(all([guard_class, controller_class, stats_class, tranquilizer, lethal]), 'saved gameplay classes load')

    def fixture():
        index = len(actors)
        guard = subsystem.spawn_actor_from_class(guard_class, unreal.Vector(index * 3000.0, 0, 100))
        controller_transform = unreal.Transform(location=unreal.Vector(index * 3000.0, 500, 100))
        statics = unreal.get_default_object(unreal.GameplayStatics)
        controller = invoke(statics, 'BeginDeferredActorSpawnFromClass',
                            guard, controller_class, controller_transform,
                            unreal.SpawnActorCollisionHandlingMethod.ALWAYS_SPAWN,
                            None, unreal.SpawnActorScaleMethod.MULTIPLY_WITH_ROOT)
        controller = invoke(statics, 'FinishSpawningActor', controller, controller_transform,
                            unreal.SpawnActorScaleMethod.MULTIPLY_WITH_ROOT)
        actors.extend([guard, controller])
        controller.possess(guard)
        invoke(guard, 'InitializeEnemyActions', controller)
        mesh = guard.get_component_by_class(unreal.SkeletalMeshComponent)
        capsule = guard.get_component_by_class(unreal.CapsuleComponent)
        stats = guard.get_component_by_class(stats_class)
        return guard, mesh, capsule, stats

    def sleeping(guard):
        return guard.actor_has_tag('SleepingGuard')

    def pending(guard):
        return unreal.SystemLibrary.is_timer_active(guard, 'EnterGuardSleep')

    def remaining(guard):
        return unreal.SystemLibrary.get_timer_remaining_time(guard, 'EnterGuardSleep')

    def snapshot(stats):
        return (stats.get_editor_property('CurrentHealth'), stats.get_editor_property('CurrentStamina'))

    def hit(guard, component, bone, location, damage_type=tranquilizer, direction=None):
        direction = direction if direction is not None else unreal.Vector(-1, 0, 0)
        normal = direction * -1.0
        statics = unreal.get_default_object(unreal.GameplayStatics)
        result = invoke(statics, 'MakeHitResult',
            True, False, 0.5, 100.0, location, location, normal, normal,
            None, guard, component, unreal.Name(bone), unreal.Name('None'), -1, 0, -1,
            location - direction * 100.0, location + direction * 100.0)
        # APawn::TakeDamage rejects editor worlds without an authoritative GameMode.
        # Dispatch the same receivers in AActor::TakeDamage order to test the saved
        # Blueprint logic without starting or modifying the user's game session.
        damage_object = unreal.get_default_object(damage_type)
        invoke(guard, 'ReceivePointDamage', 20.0, damage_object, location, normal,
               component, unreal.Name(bone), direction, None, None, result)
        invoke(guard, 'ReceiveAnyDamage', 20.0, damage_object, None, None)

    # Exercise point-damage -> generic-damage notifications in their engine order.
    guard, mesh, capsule, stats = fixture()
    before = snapshot(stats)
    body_location = mesh.get_socket_location('DEF-spine_003') + unreal.Vector(40, 0, 0)
    hit(guard, capsule, 'None', body_location)
    check(not sleeping(guard), 'a body impact does not put the guard to sleep immediately')
    check(pending(guard), 'a body impact schedules EnterGuardSleep')
    check(abs(remaining(guard) - 3.0) < 0.001, 'the body-impact timer is exactly 3 seconds')
    check(snapshot(stats) == before, 'a tranquilizer body impact preserves health and stamina')

    head_location = mesh.get_socket_location('ORG-face')
    hit(guard, mesh, 'ORG-face', head_location)
    check(sleeping(guard), 'a head impact immediately puts an already tranquilized guard to sleep')
    check(not pending(guard), 'a head impact cancels a pending body-impact timer')
    check(snapshot(stats) == before, 'a tranquilizer head impact preserves health and stamina')
    invoke(guard, 'WakeGuard')
    check(not sleeping(guard), 'the existing wake action still wakes a sleeping guard')
    check(not pending(guard), 'waking after a headshot leaves no old sleep timer')

    # A capsule collision has no BoneName: the head must still be recognized.
    guard, mesh, capsule, stats = fixture()
    head_location = mesh.get_socket_location('ORG-face')
    hit(guard, capsule, 'None', head_location + unreal.Vector(40, 0, 0))
    check(sleeping(guard), 'a head-height capsule impact is recognized as a headshot')
    check(not pending(guard), 'generic damage notification does not requeue sleep after an instant headshot')

    guard, mesh, capsule, stats = fixture()
    head_location = mesh.get_socket_location('ORG-face')
    hit(guard, capsule, 'None', head_location + unreal.Vector(0, 40, 0), direction=unreal.Vector(0, -1, 0))
    check(sleeping(guard), 'a side-on head impact resolves correctly on the Y axis')

    # An identified body part remains a body hit even when raised near the head.
    guard, mesh, capsule, stats = fixture()
    hit(guard, mesh, 'DEF-upper_arm_L', mesh.get_socket_location('ORG-face'))
    check(not sleeping(guard) and pending(guard), 'an arm impact near the head retains delayed sleep')
    check(abs(remaining(guard) - 3.0) < 0.001, 'an identified body part uses the 3-second delay')

    # The new headshot event must not convert lethal rounds into tranquilizers.
    guard, mesh, capsule, stats = fixture()
    before = snapshot(stats)
    hit(guard, mesh, 'ORG-face', mesh.get_socket_location('ORG-face'), lethal)
    check(not sleeping(guard) and not pending(guard), 'lethal head impacts do not trigger tranquilizer sleep')
    check(abs(stats.get_editor_property('CurrentHealth') - (before[0] - 20.0)) < 0.001,
          'lethal damage still follows the existing health-damage path')

    # Confirm the timer still targets the original sleep action and wake routine.
    guard, mesh, capsule, stats = fixture()
    hit(guard, capsule, 'None', mesh.get_socket_location('DEF-spine_003') + unreal.Vector(40, 0, 0))
    check(pending(guard) and not sleeping(guard), 'a fresh body impact retains delayed sleep behavior')
    invoke(guard, 'EnterGuardSleep')
    check(sleeping(guard), 'the scheduled sleep action still enters the sleeping state')


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
    unreal.log('TRANQUILIZER_VALIDATION: ' + json.dumps(report))

if not report['passed']:
    raise AssertionError('Tranquilizer validation failed; see ' + REPORT)
