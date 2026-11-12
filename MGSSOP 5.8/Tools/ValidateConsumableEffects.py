"""Validate saved consumable effects and wheel routing in an isolated Unreal world.

Run with UnrealEditor-Cmd <project> -run=pythonscript -script=<this file> -nullrhi.
No project asset is saved. Reports go to Saved/Codex/ConsumableWheel.
"""
import json
import os
import runpy
import traceback
import unreal

ROOT = '/Game/Components/'
ITEM = 'Item_3_0E272E3C4A1C988CECA1D6AF1BF53291'
AMOUNT = 'Amount_5_6CFBF00E4E01ED51230E17BD162AF331'
AMMO = 'Ammo_16_C6B7A7FD49BCB95CF15F65AA496560BD'
REPORT = os.path.join(unreal.Paths.project_saved_dir(), 'Codex', 'ConsumableWheel', 'effects-validation.json')
checks = []


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    checks.append(label)
    unreal.log('CONSUMABLE_EFFECT PASS: ' + label)


def invoke(obj, method, *args):
    return obj.call_method(method, args=args)


def run_tests():
    unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    loadout_class = unreal.load_class(None, ROOT + 'WeaponWheel/BPC_Loadout.BPC_Loadout_C')
    stats_class = unreal.load_class(None, ROOT + 'Stats/BPC_Stats.BPC_Stats_C')
    base_class = unreal.load_class(None, ROOT + 'Items/BPC_Item_Placeholder.BPC_Item_Placeholder_C')
    food_class = unreal.load_class(None, ROOT + 'Items/BPC_Item_Conserve.BPC_Item_Conserve_C')
    water_class = unreal.load_class(None, ROOT + 'Items/BPC_Item_Gourde.BPC_Item_Gourde_C')
    food = unreal.load_asset('/Game/Data/Items/DA_CannedFood')
    water = unreal.load_asset('/Game/Data/Items/DA_Canteen')
    check(food.get_editor_property('ItemComponentClass') == food_class, 'conserve data uses the healing child')
    check(water.get_editor_property('ItemComponentClass') == water_class, 'canteen data uses the stamina child')
    check(unreal.MathLibrary.class_is_child_of(food_class, base_class), 'healing component inherits item initialization and cleanup')
    check(unreal.MathLibrary.class_is_child_of(water_class, base_class), 'stamina component inherits item initialization and cleanup')
    food_defaults = unreal.get_default_object(food_class)
    water_defaults = unreal.get_default_object(water_class)
    check(food_defaults.get_editor_property('HealAmount') == 25.0, 'default healing amount is 25')
    check(water_defaults.get_editor_property('StaminaAmount') == 25.0, 'default stamina amount is 25')
    loadout_defaults = unreal.get_default_object(loadout_class)
    stats_defaults = unreal.get_default_object(stats_class)
    assert unreal.ToolsetLibrary.set_object_properties(loadout_defaults, '{"Inventory":[{}]}')
    slot_template = invoke(loadout_defaults, 'GetInvSlot', 0)
    current_actor = None

    def fixture(health=50.0, stamina=50.0, with_stats=True):
        nonlocal current_actor
        if current_actor is not None:
            actors.destroy_actor(current_actor)
        current_actor = actors.spawn_actor_from_class(unreal.Actor, unreal.Vector(0, 0, 0))
        stats = None
        if with_stats:
            for name, value in [('MaxHealth', 100.0), ('CurrentHealth', health),
                                ('MaxStamina', 100.0), ('CurrentStamina', stamina)]:
                stats_defaults.set_editor_property(name, value)
            stats = invoke(current_actor, 'AddComponentByClass', stats_class, False, unreal.Transform(), False)
        sentinel = invoke(current_actor, 'AddComponentByClass', base_class, False, unreal.Transform(), False)
        inventory = [slot_template.copy() for _ in range(6)]
        for index, data in [(3, food), (4, water)]:
            inventory[index].set_editor_property(ITEM, data)
            inventory[index].set_editor_property(AMOUNT, 2)
        loadout_defaults.set_editor_property('Inventory', inventory)
        loadout_defaults.set_editor_property('EquippedSlot', 0)
        loadout_defaults.set_editor_property('CurrentItemComp', sentinel)
        loadout_defaults.set_editor_property('ReloadLocked', False)
        loadout = invoke(current_actor, 'AddComponentByClass', loadout_class, False, unreal.Transform(), False)
        return {'actor': current_actor, 'stats': stats, 'loadout': loadout,
                'equipped': loadout.get_editor_property('CurrentItemComp'),
                'components': len(current_actor.get_components_by_class(unreal.ActorComponent))}

    def quantity(ctx, index):
        return invoke(ctx['loadout'], 'GetInvSlot', index).get_editor_property(AMOUNT)

    def intact(ctx):
        check(ctx['loadout'].get_editor_property('EquippedSlot') == 0, 'equipped slot preserved')
        check(ctx['loadout'].get_editor_property('CurrentItemComp') == ctx['equipped'], 'equipped component preserved')
        check(unreal.SystemLibrary.is_valid(ctx['equipped']), 'equipped component remains valid')
        check(len(ctx['actor'].get_components_by_class(unreal.ActorComponent)) == ctx['components'], 'temporary effect component cleaned up')

    ctx = fixture()
    invoke(ctx['loadout'], 'UseSlot', 3)
    check(ctx['stats'].get_editor_property('CurrentHealth') == 75.0, 'wheel conserve heals exactly 25')
    check(ctx['stats'].get_editor_property('MaxHealth') == 100.0, 'healing does not increase maximum health')
    check(ctx['stats'].get_editor_property('CurrentStamina') == 50.0, 'conserve leaves stamina unchanged')
    check(quantity(ctx, 3) == 1, 'successful healing consumes exactly one conserve')
    check(invoke(ctx['loadout'], 'GetSlot', 3).get_editor_property(AMMO) == 1, 'wheel counter updates after healing')
    intact(ctx)

    ctx = fixture(health=95.0)
    check(invoke(ctx['loadout'], 'UseConsumable', 3) is True, 'partial healing succeeds near maximum health')
    check(ctx['stats'].get_editor_property('CurrentHealth') == 100.0, 'healing clamps to maximum health')
    check(quantity(ctx, 3) == 1, 'partial healing consumes one item')
    check(invoke(ctx['loadout'], 'UseConsumable', 3) is False, 'full health refuses another conserve')
    check(quantity(ctx, 3) == 1, 'full health preserves the remaining conserve')
    intact(ctx)

    ctx = fixture()
    invoke(ctx['loadout'], 'UseSlot', 4)
    check(ctx['stats'].get_editor_property('CurrentStamina') == 75.0, 'wheel canteen restores exactly 25 stamina')
    check(ctx['stats'].get_editor_property('MaxStamina') == 100.0, 'canteen does not increase maximum stamina')
    check(ctx['stats'].get_editor_property('CurrentHealth') == 50.0, 'canteen leaves health unchanged')
    check(quantity(ctx, 4) == 1, 'successful stamina restoration consumes one canteen')
    intact(ctx)

    ctx = fixture(stamina=95.0)
    check(invoke(ctx['loadout'], 'UseConsumable', 4) is True, 'partial stamina restoration succeeds')
    check(ctx['stats'].get_editor_property('CurrentStamina') == 100.0, 'stamina restoration clamps to maximum')
    check(invoke(ctx['loadout'], 'UseConsumable', 4) is False, 'full stamina refuses another canteen')
    check(quantity(ctx, 4) == 1, 'full stamina preserves the remaining canteen')
    intact(ctx)

    ctx = fixture(health=100.0, stamina=100.0)
    invoke(ctx['loadout'], 'UseSlot', 3)
    invoke(ctx['loadout'], 'UseSlot', 4)
    check(quantity(ctx, 3) == 2 and quantity(ctx, 4) == 2, 'wheel validation at full stats consumes no items')
    intact(ctx)

    ctx = fixture(with_stats=False)
    check(invoke(ctx['loadout'], 'UseConsumable', 3) is False, 'conserve refuses use without stats')
    check(invoke(ctx['loadout'], 'UseConsumable', 4) is False, 'canteen refuses use without stats')
    check(quantity(ctx, 3) == 2 and quantity(ctx, 4) == 2, 'missing stats preserves both quantities')
    intact(ctx)

    ctx = fixture()
    for method in ['Heal', 'RestoreStamina']:
        check(invoke(ctx['stats'], method, 0.0) is False, method + ' refuses zero amount')
        check(invoke(ctx['stats'], method, -25.0) is False, method + ' refuses negative amount')
    check(ctx['stats'].get_editor_property('CurrentHealth') == 50.0 and
          ctx['stats'].get_editor_property('CurrentStamina') == 50.0, 'invalid amounts leave both stats unchanged')
    check(invoke(ctx['stats'], 'Heal', 1000.0) is True, 'large healing succeeds')
    check(invoke(ctx['stats'], 'RestoreStamina', 1000.0) is True, 'large stamina restoration succeeds')
    check(ctx['stats'].get_editor_property('CurrentHealth') == 100.0 and
          ctx['stats'].get_editor_property('CurrentStamina') == 100.0, 'large amounts remain capped')

    food_defaults.set_editor_property('HealAmount', 10.0)
    water_defaults.set_editor_property('StaminaAmount', 40.0)
    ctx = fixture()
    invoke(ctx['loadout'], 'UseSlot', 3)
    invoke(ctx['loadout'], 'UseSlot', 4)
    check(ctx['stats'].get_editor_property('CurrentHealth') == 60.0, 'custom HealAmount is applied')
    check(ctx['stats'].get_editor_property('CurrentStamina') == 90.0, 'custom StaminaAmount is applied')
    intact(ctx)
    food_defaults.set_editor_property('HealAmount', 0.0)
    ctx = fixture()
    check(invoke(ctx['loadout'], 'UseConsumable', 3) is False, 'zero configured healing refuses consumption')
    check(quantity(ctx, 3) == 2, 'zero configured healing preserves quantity')
    intact(ctx)
    food_defaults.set_editor_property('HealAmount', 25.0)
    water_defaults.set_editor_property('StaminaAmount', 25.0)
    actors.destroy_actor(current_actor)

    # Reuse the routing, inventory, lock, and cleanup regression suite.
    runpy.run_path(os.path.join(unreal.Paths.project_dir(), 'Tools', 'ValidateConsumableWheel.py'))
    regression = os.path.join(unreal.Paths.project_saved_dir(), 'Codex', 'ConsumableWheel', 'validation.json')
    with open(regression, encoding='utf-8') as stream:
        result = json.load(stream)
    check(result['passed'], 'existing consumable wheel regression suite passes')
    return len(result['checks'])


report = {'passed': False, 'checks': checks}
try:
    report['wheel_checks'] = run_tests()
    report['passed'] = True
except Exception:
    report['error'] = traceback.format_exc()
    unreal.log_error(report['error'])
finally:
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, 'w', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    unreal.log('CONSUMABLE_EFFECT_RESULT: ' + json.dumps(report))
if not report['passed']:
    raise RuntimeError('Consumable effect validation failed; see ' + REPORT)
