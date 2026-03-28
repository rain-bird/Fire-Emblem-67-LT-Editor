# Fire-Emblem-67-LT-Editor
The modified version of the Lex Talionis Fire Emblem editor for usage with the Fire Emblem 67 project by Donlot.

BASE CHANGES BEFORE ALL FUTURE COMMITS
=== Unit Funds ===
unit.py - UnitObject: Units now have a personal_funds attribute
info_menu_state.py - create_personal_data_surf: Began to make unit personal_funds display, but didn't finish it
general_states.py - ShopState: Every reference to party funds is now a reference to a unit's personal_funds
menu_options.py - ValueItemOption: Now references a unit's personal_funds instead of party funds when determining if it should gray out an item's cost
menu_options.py - RepairValueItemOption: The same as ValueItemOption, though I haven't tested this change
action.py - GainMoney: Now modifies a unit's personal_funds instead of party funds. This means you also have to provide the unit to modify now
event_functions.py - give_money: Same as GainMoney
event_commands.py - GiveMoney: Same as GainMoney

THE CHANGES TO EVENT_FUNCTIONS AND EVENT_COMMANDS MEAN THAT WHEN USING "give_money" IN THE EDITOR, YOU HAVE TO SUPPLY A UNIT AS ONE OF THE ARGUMENTS! The editor should tell you this itself.

=== Personal Deposits ===
item.py - ItemObject: Now has a ".depositor" attribute for tracking who deposited this item into the convoy
action.py - PutItemInConvoy, TradeItemWithConvoy and StoreItem: The moved item now updates its .depoistor attribute
menus.py - Convoy: The convoy class has been mildly hacked so that units can only access items that they have deposited into the convoy

=== Other ===
info_menu_state.py - create_personal_data_surf: Changed the order of unit stats to match FE GBA (including hiding Rating).
general_states.py - ItemDiscardState: If convoy access is enabled, the unit can ALWAYS send items to the convoy if their inventory is full

And maybe some other stuff I don't remember. I didn't actually write down every file I modified as I went, I had to go back through and check them for differences just now.
