"""Run with UnrealEditor-Cmd <project> -run=pythonscript -script=<this file> -nullrhi.

Exercises the saved Blueprints in a temporary editor world. Does not save assets.
Results are written to Saved/Codex/ConsumableWheel/validation.json.
"""
import json
import os
import traceback
import unreal

ROOT = '/Game/Components/'
ITEM = 'Item_3_0E272E3C4A1C988CECA1D6AF1BF53291'
AMOUNT = 'Amount_5_6CFBF00E4E01ED51230E17BD162AF331'
AMMO = 'Ammo_16_C6B7A7FD49BCB95CF15F65AA496560BD'
KIND = 'Kind_39_EDEBA60F43DFEA7415BB0B9B90D9F862'
REPORT = os.path.join(unreal.Paths.project_saved_dir(), 'Codex', 'ConsumableWheel', 'validation.json')
results = []


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    results.append(label)
    unreal.log('CONSUMABLE_TEST PASS: ' + label)


def invoke(obj, method, *args):
    return obj.call_method(method, args=args)


def test():
    unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    actor = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
        unreal.Actor, unreal.Vector(0, 0, 0))
    loadout_class = unreal.load_class(None, ROOT + 'WeaponWheel/BPC_Loadout.BPC_Loadout_C')
    item_class = unreal.load_class(None, ROOT + 'Items/BPC_Item_Placeholder.BPC_Item_Placeholder_C')
    stats_class = unreal.load_class(None, ROOT + 'Stats/BPC_Stats.BPC_Stats_C')
    stats_defaults = unreal.get_default_object(stats_class)
    for name, value in [('MaxHealth', 1000.0), ('CurrentHealth', 100.0),
                        ('MaxStamina', 1000.0), ('CurrentStamina', 100.0)]:
        stats_defaults.set_editor_property(name, value)
    invoke(actor, 'AddComponentByClass', stats_class, False, unreal.Transform(), False)
    sentinel = invoke(actor, 'AddComponentByClass', item_class, False, unreal.Transform(), False)
    canteen = unreal.load_asset('/Game/Data/Items/DA_Canteen')
    canned = unreal.load_asset('/Game/Data/Items/DA_CannedFood')
    rifle = unreal.load_asset('/Game/Data/Items/DA_AK47')
    # Change only this commandlet's in-memory class defaults, then instantiate
    # the production component. Runtime variables are not editor-instance editable.
    defaults = unreal.get_default_object(loadout_class)
    if len(defaults.get_editor_property('Inventory')) == 0:
        assert unreal.ToolsetLibrary.set_object_properties(defaults, '{"Inventory":[{}]}')
    template = invoke(defaults, 'GetInvSlot', 0)
    inventory = [template.copy() for _ in range(7)]
    for entry in inventory:
        entry.set_editor_property(ITEM, None)
        entry.set_editor_property(AMOUNT, 0)
        entry.set_editor_property('Loaded_7_EC960F0D460E5C6B797955873706C903', 0)
        entry.set_editor_property('WeaponActor_10_1EA71A084662658EE85D0DAF8B9AA414', None)
    invalid_item = unreal.get_default_object(canteen.get_class())
    invalid_item.set_editor_property('SlotType', canteen.get_editor_property('SlotType'))
    invalid_item.set_editor_property('ItemComponentClass', unreal.SceneComponent.static_class())
    for index, item, quantity in [(0, rifle, 1), (3, canned, 3), (4, canteen, 3), (5, canned, 2), (6, invalid_item, 2)]:
        inventory[index].set_editor_property(ITEM, item)
        inventory[index].set_editor_property(AMOUNT, quantity)
    defaults.set_editor_property('Inventory', inventory)
    defaults.set_editor_property('EquippedSlot', 0)
    defaults.set_editor_property('CurrentItemComp', sentinel)
    defaults.set_editor_property('ReloadLocked', False)
    loadout = invoke(actor, 'AddComponentByClass', loadout_class, False, unreal.Transform(), False)
    check(len(loadout.get_editor_property('Inventory')) == 7, 'initialize isolated inventory')

    def slot(index):
        return invoke(loadout, 'GetInvSlot', index)

    def amount(index):
        return slot(index).get_editor_property(AMOUNT)

    def count():
        return len(actor.get_components_by_class(unreal.ActorComponent))

    baseline = count()
    equipped_before = loadout.get_editor_property('CurrentItemComp')

    def intact():
        check(loadout.get_editor_property('EquippedSlot') == 0, 'equipped slot preserved')
        check(loadout.get_editor_property('CurrentItemComp') == equipped_before, 'equipped component preserved')
        check(unreal.SystemLibrary.is_valid(equipped_before), 'equipped component remains valid')
        check(count() == baseline, 'temporary components cleaned up')

    check(invoke(sentinel, 'TryUse') is False, 'uninitialized item refuses use')
    invoke(loadout, 'UseSlot', 3)
    check(amount(3) == 2, 'consumable in a Throwable layout slot uses the item category')
    intact()
    displayed = invoke(loadout, 'GetSlot', 3)
    check(displayed.get_editor_property(AMMO) == amount(3), 'wheel counter reflects actual inventory quantity')
    check(displayed.get_editor_property(KIND) == 2, 'wheel slot category follows actual consumable')
    check(invoke(loadout, 'UseConsumable', 4) is True, 'canteen use succeeds')
    check(amount(4) == 2, 'canteen decremented exactly once')
    intact()
    invoke(loadout, 'UseSlot', 4)
    check(amount(4) == 1, 'wheel entry uses canteen directly')
    intact()
    invoke(loadout, 'UseSlot', 4)
    check(amount(4) == 0 and slot(4).get_editor_property(ITEM) is None, 'last unit clears slot')
    intact()
    check(invoke(loadout, 'UseConsumable', 4) is False, 'empty slot refuses use')
    check(invoke(loadout, 'UseConsumable', -1) is False, 'negative slot refuses use')
    check(invoke(loadout, 'UseConsumable', 7) is False, 'out-of-range slot refuses use')
    check(invoke(loadout, 'UseConsumable', 0) is False, 'weapon refuses consumable path')
    check(amount(0) == 1, 'weapon inventory entry preserved')

    invoke(loadout, 'UseSlot', 5)
    check(amount(5) == 1, 'wheel entry uses canned food directly (quantity=%s, locked=%s)' % (amount(5), loadout.get_editor_property('ReloadLocked')))
    intact()

    check(invoke(loadout, 'UseConsumable', 6) is False, 'incompatible component refuses use')
    check(amount(6) == 2, 'incompatible component preserves quantity')
    intact()
    invalid_item.set_editor_property('ItemComponentClass', None)
    check(invoke(loadout, 'UseConsumable', 6) is False, 'missing component class refuses use')
    check(amount(6) == 2, 'missing component class preserves quantity')

    factory = unreal.BlueprintFactory()
    factory.set_editor_property('parent_class', item_class)
    rejection = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        'BP_CodexRejectedUse', '/Game/__CodexValidationTransient', unreal.Blueprint, factory)
    assert rejection, 'Could not construct the unsaved rejection Blueprint'
    rejection_graph = unreal.BlueprintEditorLibrary.add_function_override(rejection, 'TryUse')
    editor = unreal.BlueprintGraphEditor.get_graph_editor(rejection_graph)
    # Override creation inserts a parent call by default. Replace it with an
    # explicit refusal to exercise the caller's no-consumption branch.
    editor.remove_nodes([n for n in editor.list_all_nodes()
                         if n.get_class().get_name() != 'K2Node_FunctionEntry'])
    refused = editor.add_return_node()
    assert refused.find_input_pin('Success').set_pin_value('false')
    assert editor.find_graph_entry_pin().try_create_connection(refused.find_execute_pin())
    unreal.BlueprintEditorLibrary.compile_blueprint(rejection)
    invalid_item.set_editor_property('ItemComponentClass', rejection.generated_class())
    check(invoke(loadout, 'UseConsumable', 6) is False, 'TryUse rejection propagates')
    check(amount(6) == 2, 'TryUse rejection preserves quantity')
    intact()

    # Changing a class default through the editor may propagate to existing
    # archetype instances, so run this independent fixture after all other cases.
    defaults.set_editor_property('ReloadLocked', True)
    locked = invoke(actor, 'AddComponentByClass', loadout_class, False, unreal.Transform(), False)
    check(invoke(locked, 'UseConsumable', 5) is False, 'reload lock blocks use')
    check(invoke(locked, 'GetInvSlot', 5).get_editor_property(AMOUNT) == 2, 'reload lock preserves quantity')
    invoke(locked, 'K2_DestroyComponent', locked)


report = {'passed': False, 'checks': results}
try:
    test()
    report['passed'] = True
except Exception:
    report['error'] = traceback.format_exc()
    unreal.log_error(report['error'])
finally:
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, 'w', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    unreal.log('CONSUMABLE_TEST_RESULT: ' + json.dumps(report))
if not report['passed']:
    raise RuntimeError('Consumable wheel validation failed; see ' + REPORT)
