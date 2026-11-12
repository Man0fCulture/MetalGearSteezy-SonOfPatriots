"""Exercise the saved peanut bar and BP_Player in an isolated editor world.

Run with UnrealEditor-Cmd <project> -run=pythonscript -script=<this file> -nullrhi.
Test setters exist only in this process; no modified asset or map is saved.
"""
import json
import os
import traceback
import unreal

REPORT = os.path.join(unreal.Paths.project_saved_dir(), 'Codex', 'ConsumableWheel', 'peanut-validation.json')
ITEM = 'Item_3_0E272E3C4A1C988CECA1D6AF1BF53291'
AMOUNT = 'Amount_5_6CFBF00E4E01ED51230E17BD162AF331'
checks = []


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    checks.append(label)
    unreal.log('PEANUT_BAR PASS: ' + label)


def invoke(obj, method, *args):
    return obj.call_method(method, args=args)


def add_setter(blueprint, name, literal=None, suffix=''):
    editor = unreal.BlueprintGraphEditor.create_and_edit_function_graph(blueprint, 'CodexTestSet' + name + suffix)
    node = editor.add_set_member_variable_node(name)
    value = node.find_input_pin(name)
    if literal is None:
        parameter = editor.add_graph_input_parameter('Value', value.get_pin_type())
        assert parameter.try_create_connection(value)
    else:
        assert value.set_pin_value(literal)
    assert editor.find_graph_entry_pin().try_create_connection(node.find_execute_pin())


def run_tests():
    unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    paths = {
        'player': '/Game/Actors/Characters/Player/BP_Player',
        'stats': '/Game/Components/Stats/BPC_Stats',
        'loadout': '/Game/Components/WeaponWheel/BPC_Loadout',
        'equipment': '/Game/Components/Weapon/BPC_Equipment',
    }
    # Resolve the existing equipment component's asset rather than assuming its folder.
    player_asset = unreal.load_asset(paths['player'])
    player_class = unreal.load_class(None, paths['player'] + '.BP_Player_C')
    probe = actors.spawn_actor_from_class(player_class, unreal.Vector(0, 0, 0))
    equipment = probe.get_editor_property('BPC_Equipment')
    paths['equipment'] = equipment.get_class().get_path_name().split('.')[0]
    actors.destroy_actor(probe)
    assets = {key: unreal.load_asset(path) for key, path in paths.items()}
    for name in ['bIsSprinting', 'bStealthHeld']:
        add_setter(assets['player'], name)
    for index, label in [(0, 'Standing'), (1, 'Crouch'), (2, 'Prone')]:
        add_setter(assets['player'], 'CurrentPosture', 'NewEnumerator' + str(index), label)
    for name in ['MaxHealth', 'CurrentHealth', 'CurrentStamina']:
        add_setter(assets['stats'], name)
    for name in ['Inventory', 'EquippedSlot', 'CurrentItemComp', 'ReloadLocked']:
        add_setter(assets['loadout'], name)
    add_setter(assets['equipment'], 'bAiming')
    for asset in assets.values():
        unreal.BlueprintEditorLibrary.compile_blueprint(asset)
    classes = {key: unreal.load_class(None, path + '.' + path.split('/')[-1] + '_C') for key, path in paths.items()}
    bar_class = unreal.load_class(None, '/Game/Components/Items/BPC_Item_PeanutBar.BPC_Item_PeanutBar_C')
    base_class = unreal.load_class(None, '/Game/Components/Items/BPC_Item_Placeholder.BPC_Item_Placeholder_C')
    bar = unreal.load_asset('/Game/Data/Items/DA_Bar')
    check(bar.get_editor_property('ItemComponentClass') == bar_class, 'DA_Bar uses the peanut bar effect')
    check(unreal.MathLibrary.class_is_child_of(bar_class, base_class), 'bar inherits item initialization and disposal')
    defaults = unreal.get_default_object(bar_class)
    for name, expected in [('HealAmount', 25.0), ('SprintSpeedBonus', 50.0), ('BuffDuration', 30.0)]:
        check(defaults.get_editor_property(name) == expected, name + ' default is ' + str(expected))
    loadout_defaults = unreal.get_default_object(classes['loadout'])
    if not loadout_defaults.get_editor_property('Inventory'):
        assert unreal.ToolsetLibrary.set_object_properties(loadout_defaults, '{"Inventory":[{}]}')
    template = invoke(loadout_defaults, 'GetInvSlot', 0)
    player = actors.spawn_actor_from_class(classes['player'], unreal.Vector(0, 0, 0))
    stats = player.get_component_by_class(classes['stats'])
    check(stats is not None, 'actual BP_Player has a stats component')
    loadout = player.get_component_by_class(classes['loadout'])
    if loadout is None:
        loadout = invoke(player, 'AddComponentByClass', classes['loadout'], False, unreal.Transform(), False)
    equipment = player.get_component_by_class(classes['equipment'])
    movement = player.get_editor_property('CharacterMovement')
    sentinel = invoke(player, 'AddComponentByClass', base_class, False, unreal.Transform(), False)

    def set_value(obj, name, value):
        invoke(obj, 'CodexTestSet' + name, value)

    def inventory(amount=3):
        entries = [template.copy() for _ in range(6)]
        entries[5].set_editor_property(ITEM, bar)
        entries[5].set_editor_property(AMOUNT, amount)
        set_value(loadout, 'Inventory', entries)

    def quantity():
        return invoke(loadout, 'GetInvSlot', 5).get_editor_property(AMOUNT)

    def state(sprint=False, aim=False, stealth=False, posture='Standing'):
        set_value(player, 'bIsSprinting', sprint)
        set_value(player, 'bStealthHeld', stealth)
        set_value(equipment, 'bAiming', aim)
        invoke(player, 'CodexTestSetCurrentPosture' + posture)
        invoke(player, 'UpdateMoveSpeed')
        return movement.get_editor_property('MaxWalkSpeed')

    def intact():
        check(loadout.get_editor_property('EquippedSlot') == 0, 'equipped slot is preserved')
        check(loadout.get_editor_property('CurrentItemComp') == sentinel, 'equipped component is preserved')
        check(unreal.SystemLibrary.is_valid(sentinel), 'equipped component stays valid')
        check(len(player.get_components_by_class(unreal.ActorComponent)) == component_count, 'temporary bar component is disposed')

    set_value(stats, 'MaxHealth', 100.0)
    set_value(stats, 'CurrentHealth', 50.0)
    set_value(loadout, 'EquippedSlot', 0)
    set_value(loadout, 'CurrentItemComp', sentinel)
    set_value(loadout, 'ReloadLocked', False)
    inventory()
    component_count = len(player.get_components_by_class(unreal.ActorComponent))
    base_sprint = player.get_editor_property('Sprint')
    check(player.get_editor_property('StomachAcheDisplayName') == 'Stomach Ache', 'status display name is English')
    check(not player.get_editor_property('StomachAcheActive'), 'status starts inactive')
    baseline = {label: state(**kwargs) for label, kwargs in [
        ('walk', {}), ('sprint', {'sprint': True}), ('aim', {'sprint': True, 'aim': True}),
        ('stealth', {'sprint': True, 'stealth': True}), ('crouch', {'sprint': True, 'posture': 'Crouch'}),
        ('prone', {'sprint': True, 'posture': 'Prone'})]}
    check(baseline['sprint'] == base_sprint, 'normal sprint uses the configured base speed')
    state(sprint=True)
    invoke(loadout, 'UseSlot', 5)
    check(stats.get_editor_property('CurrentHealth') == 75.0, 'wheel use restores exactly 25 HP')
    check(stats.get_editor_property('MaxHealth') == 100.0, 'maximum health remains unchanged')
    check(quantity() == 2, 'wheel use consumes exactly one bar')
    check(player.get_editor_property('StomachAcheActive'), 'wheel use activates Stomach Ache on the player')
    check(player.get_editor_property('StomachAcheSprintBonus') == 50.0, 'player holds the additive 50 bonus')
    check(movement.get_editor_property('MaxWalkSpeed') == base_sprint + 50.0, 'active sprint immediately gains 50 speed')
    check(abs(invoke(player, 'GetStomachAcheRemainingTime') - 30.0) < 0.05, 'player timer is set to 30 seconds')
    intact()
    for label, kwargs in [('walk', {}), ('aim', {'sprint': True, 'aim': True}),
                          ('stealth', {'sprint': True, 'stealth': True}),
                          ('crouch', {'sprint': True, 'posture': 'Crouch'}),
                          ('prone', {'sprint': True, 'posture': 'Prone'})]:
        check(state(**kwargs) == baseline[label], label + ' speed keeps its existing behavior')
    check(state(sprint=True) == base_sprint + 50.0, 'reentering sprint retains the bonus')
    check(invoke(loadout, 'UseConsumable', 5) is True, 'a second bar refreshes the effect')
    check(stats.get_editor_property('CurrentHealth') == 100.0, 'second bar heals to maximum')
    check(quantity() == 1, 'refresh consumes exactly one bar')
    check(movement.get_editor_property('MaxWalkSpeed') == base_sprint + 50.0, 'refresh does not stack the speed bonus')
    check(invoke(loadout, 'UseConsumable', 5) is True, 'full health still permits the sprint effect')
    check(quantity() == 0, 'full-health buff consumes one bar')
    check(invoke(loadout, 'UseConsumable', 5) is False, 'empty slot refuses use')
    intact()
    invoke(player, 'ClearStomachAche')
    check(not player.get_editor_property('StomachAcheActive'), 'expiry callback clears the active flag')
    check(player.get_editor_property('StomachAcheSprintBonus') == 0.0, 'expiry callback removes the speed bonus')
    check(movement.get_editor_property('MaxWalkSpeed') == base_sprint, 'expiry callback restores normal sprint immediately')
    check(invoke(player, 'GetStomachAcheRemainingTime') == 0.0, 'clearing removes the player timer')
    for bonus, duration in [(0.0, 30.0), (-50.0, 30.0), (50.0, 0.0), (50.0, -1.0)]:
        check(invoke(player, 'ApplyStomachAche', bonus, duration) is False, 'invalid bonus/duration is refused: ' + str((bonus, duration)))
    check(not player.get_editor_property('StomachAcheActive'), 'invalid effects leave player unchanged')
    inventory(1)
    set_value(loadout, 'ReloadLocked', True)
    health = stats.get_editor_property('CurrentHealth')
    check(invoke(loadout, 'UseConsumable', 5) is False, 'reload lock refuses bar consumption')
    check(quantity() == 1 and stats.get_editor_property('CurrentHealth') == health, 'refused use preserves item and health')
    check(not player.get_editor_property('StomachAcheActive'), 'refused use applies no bonus')
    intact()
    actors.destroy_actor(player)


result = {'passed': False, 'checks': checks}
try:
    run_tests()
    result['passed'] = True
except Exception:
    result['error'] = traceback.format_exc()
    unreal.log_error(result['error'])
finally:
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, 'w', encoding='utf-8') as report_file:
        json.dump(result, report_file, indent=2)
    unreal.log('PEANUT_BAR_REPORT: ' + REPORT)
if not result['passed']:
    raise RuntimeError('Peanut bar validation failed; inspect ' + REPORT)
