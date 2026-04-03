# Fire-Emblem-67-LT-Editor
The modified version of the Lex Talionis Fire Emblem fangame maker for usage with the Fire Emblem 67 project by Donlot.
To my knowledge no Windows executable is included. You're going to have to install Python to run this.

## CHANGES FROM BASE LEX TALIONIS
### === Unit Funds ===
 - unit.py - UnitObject: Units now have a "personal_funds" attribute<br/>
 - info_menu_state.py - create_personal_data_surf: Began to make unit personal_funds display, but didn't finish it<br/>
 - general_states.py - ShopState: Every reference to party funds is now a reference to a unit's personal_funds<br/>
 - menu_options.py - ValueItemOption: Now references a unit's personal_funds instead of party funds when determining if it should gray out an item's cost<br/>
 - menu_options.py - RepairValueItemOption: The same as ValueItemOption, though I haven't tested this change<br/>
 - action.py - GainMoney: Now modifies a unit's personal_funds instead of party funds. This means you also have to provide the unit to modify now<br/>
 - event_functions.py - give_money: Same as GainMoney<br/>
 - event_commands.py - GiveMoney: Same as GainMoney<br/>

The changes to event_functions.py and event_commands.py mean that when using "give_money" in the event editor, you MUST supply a unit as one of the arguments! The editor should tell you this itself.<br/>

### === Personal Deposits ===
 - item.py - ItemObject: Items now have a "depositor" attribute for tracking who deposited this item into the convoy<br/>
 - action.py - PutItemInConvoy, TradeItemWithConvoy and StoreItem: The moved item now updates its .depoistor attribute<br/>
 - menus.py - Convoy: The convoy class has been mildly hacked so that units can only access items that they have deposited into the convoy<br/>

### === Shop Changes ===
 - menus.py - Shop: decrement_stock and create_options have been changed so that when an item is out of stock, it will be immediately removed from the list.<br/>
 - general_states.py - ShopState: changed to support the changes to menus.py.<br/>
 - menu_options.py - StockValueItemOption: If an item is in stock its stock number will always display in white, even if the item isn't compatible with the unit accessing the shop.<br/>

### === Repair Shop Changes ===
 - menu_options.py - RepairValueItemOption: If an item is able to be repaired, its name and uses will always display in white. Items will also prefer to display their broken_price (useful for FE 67's Broken Items).<br/>
 - general_states.py - RepairShopState: Updated to reference unit personal funds instead of party funds. The screen will also refresh upon performing a repair, and items with a broken_price greater than 0 will pass their   - broken_price as the cost of their repair (also useful for FE 67's Broken Items).<br/>
 - item_funcs.py - can_repair: Returns true if the item is a valid Broken Item (defined by the item having a broken_price greater than 0).<br/>
 - action.py - RepairItem: If a valid Broken Item (defined by the item having a broken_price greater than 0) is passed, the repair shop can now convert that item into a fixed item (defined by broken_nid) with its original  - name (defined by broken_name). The item's kill count (defined by kills) is also preserved. You can't reverse fixing a Broken Item though.<br/>
 - item.py - ItemObject: Items now have "broken_nid," "broken_name," and "broken_price" attributes for usage within the above changes.<br/>
 - event_functions.py - repair_shop: A new function for opening the repair shop without having to jump through several dozen layers of bullshit.<br/>
 - event_commands.py - RepairShop: A new command so you can now open the repair shop during ordinary events.<br/>

Also added a portrait of Merlinus that is used by the Repair Shop.<br/>

### === Combat Changes ===
 - combat_calcs.py - outspeed: Units can only double in combat if they have a skill with the nid "Pursuit." Units that meet this criteria can also get doubled if they have low enough negative Action Speed. HOWEVER; if either unit has a skill with the nid "Wary_Fighter," then doubling can NEVER occur for either unit.<br/>

Ordinarily I wouldn't dedicate a whole section to one change, but this one was a big one. Also making this function based on nids probably isn't good practice, but it was definitely easy.<br/>

### === Other ===
 - info_menu_state.py - create_personal_data_surf: Changed the order of unit stats to match FE GBA (including hiding Rating).<br/>
 - general_states.py - ItemDiscardState: If convoy access is enabled, units can ALWAYS send items to the convoy if their inventory is full.<br/>
 - unit_funcs.py check_broad_focus: A new function for counting how many units within a specified area, regardless of if they're an ally, have a specified tag.<br/>
 - item.py - ItemObject: Items also have a "kills" attribute for usage within the FE 67 project's kill-based crit system.<br/>

And maybe some other stuff I don't remember. I didn't actually write down every file I modified as I went, I had to go back through and check them for differences just now.
