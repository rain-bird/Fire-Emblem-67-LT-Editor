
from __future__ import annotations

import logging
from typing import List, Optional, Tuple, TYPE_CHECKING

from app.constants import WINHEIGHT, WINWIDTH
from app.data.database.database import DB
from app.data.resources.resources import RESOURCES
from app.engine import (background, combat_calcs, engine, equations, gui,
                        help_menu, icons, image_mods, item_funcs, item_system,
                        skill_system, text_funcs, unit_funcs)
from app.engine.fluid_scroll import FluidScroll
from app.engine.game_menus.icon_options import BasicItemOption
from app.engine.game_menus.uses_display_config import ItemOptionModes
from app.engine.game_state import game
from app.engine.graphics.ingame_ui.build_groove import build_groove
from app.engine.graphics.text.text_renderer import render_text, text_width
from app.engine.info_menu.info_graph import InfoGraph, info_states
from app.engine.info_menu.info_menu_portrait import InfoMenuPortrait
from app.engine.input_manager import get_input_manager
from app.engine.objects.unit import UnitObject
from app.engine.sound import get_sound_thread
from app.engine.sprites import SPRITES
from app.engine.state import State
from app.engine.text_evaluator import TextEvaluator
from app.utilities import utils
from app.utilities.enums import HAlignment
from app.engine.fonts import FONT
from app.engine.info_menu.multi_desc import PageType, build_dialog_list

if TYPE_CHECKING:
    from app.engine.objects.item import ItemObject

class InfoMenuState(State):
    name = 'info_menu'
    in_level = False
    show_map = False 

    def _init(self):
        """
        Determines which stats are left stats, right stats, and/or hidden stats
        for use when drawing within this state.

        Necessary to wrap this in a function that's called when the info menu starts up
        because otherwise starting up the info menu, then changing the stat nids, and then
        starting up the info menu again will break which stats are actually available
        """
        left_stats = [stat.nid for stat in DB.stats if stat.position == 'left']
        if len(left_stats) >= 7:
            _extra_stat_row = True
            # If we have 7 or more left stats, use 7 rows
            right_stats = left_stats[7:]
        else:  # Otherwise, just use the 6 rows
            _extra_stat_row = False
            right_stats = left_stats[6:]
        right_stats += [stat.nid for stat in DB.stats if stat.position == 'right']
        # Make sure we only display up to 6 or 7 on each
        if _extra_stat_row:
            left_stats = left_stats[:7]
            right_stats = right_stats[:7]
        else:
            left_stats = left_stats[:6]
            right_stats = right_stats[:6]
        self._extra_stat_row = _extra_stat_row
        self.left_stats = left_stats
        self.right_stats = right_stats

    def create_background(self):
        panorama = RESOURCES.panoramas.get('info_menu_background')
        if not panorama:
            panorama = RESOURCES.panoramas.get('default_background')
        if panorama:
            self.bg = background.PanoramaBackground(panorama, autoscale=False)
        else:
            self.bg = None

    def start(self):
        self._init()
        self.mouse_indicator = gui.MouseIndicator()
        self.create_background()

        # Unit to be displayed
        self.unit: UnitObject = game.memory.get('current_unit')
        self.scroll_units = game.memory.get('scroll_units')
        if self.scroll_units is None:
            self.scroll_units = [unit for unit in game.units if not unit.dead and unit.team == self.unit.team and unit.party == self.unit.party]
            if self.unit.position:
                self.scroll_units = [unit for unit in self.scroll_units if unit.position and game.board.in_vision(unit.position)]
        self.scroll_units = [unit for unit in self.scroll_units if 'Tile' not in unit.tags]
        game.memory['scroll_units'] = None

        self.state = game.memory.get('info_menu_state', info_states[0])
        if self.state == 'notes' and not (DB.constants.value('unit_notes') and self.unit.notes):
            self.state = 'personal_data'
        self.growth_flag = False

        self.fluid = FluidScroll(200, 1)

        self.build_arrows()

        self.logo = None
        image = SPRITES.get('info_title_personal_data')
        self.logo = gui.Logo(image, (314, 16))

        self.info_graph = InfoGraph()
        self.info_flag = False
        self.info_graph.set_current_state(self.state)
        self.reset_surfs()

        # For transitions between states
        self.rescuer = None  # Keeps track of the rescuer if we are looking at the traveler
        self.next_unit = None
        self.next_state = None
        self.scroll_offset_x = 0
        self.scroll_offset_y = 0
        self.transition = None
        self.transition_counter = 0
        self.transparency = 0

        game.state.change('transition_in')
        return 'repeat'

    def begin(self):
        self.fluid.reset_on_change_state()

    def reset_surfs(self, keep_last_info_graph_aabb=False):
        self.info_graph.clear(keep_last_aabb=keep_last_info_graph_aabb)
        self.portrait_surf = None
        self.weapon_stat_surf = None
        self.current_portrait = None

        self.personal_data_surf: engine.Surface = None
        self.growths_surf: engine.Surface = None
        self.wexp_surf: engine.Surface = None
        self.equipment_surf: engine.Surface = None
        self.support_surf: engine.Surface = None
        self.skill_surf: engine.Surface = None
        self.class_skill_surf: engine.Surface = None
        self.fatigue_surf: engine.Surface = None
        self.notes_surf: engine.Surface = None

    def build_arrows(self):
        self.left_arrow = gui.ScrollArrow('left', (103, 3))
        self.right_arrow = gui.ScrollArrow('right', (217, 3), 0.5)

    def back(self):
        get_sound_thread().play_sfx('Select 4')
        game.memory['info_menu_state'] = self.state
        #If this unit is currently rescued, focus on their rescuer. Otherwise, focus on this unit
        if self.rescuer:
            game.memory['current_unit'] = self.rescuer
            if self.rescuer.position and not game.is_roam():
                # Move camera to the new character unless it's a free roam, in which case we just stay on the free roamer
                game.cursor.set_pos(self.rescuer.position)
        else:
            game.memory['current_unit'] = self.unit
            if self.unit.position and not game.is_roam():
                # Move camera to the new character unless it's a free roam, in which case we just stay on the free roamer
                game.cursor.set_pos(self.unit.position)
        game.state.change('transition_pop')

    def take_input(self, event):
        first_push = self.fluid.update()
        directions = self.fluid.get_directions()

        self.handle_mouse()
        if self.info_flag:
            if event == 'INFO' or event == 'BACK':
                get_sound_thread().play_sfx('Info Out')
                self.info_graph.set_transition_out()
                self.info_flag = False
                return
            
            if event == 'AUX':
                self.info_graph.switch_info()
                get_sound_thread().play_sfx('Select 6')

            if 'RIGHT' in directions:
                if self.info_graph.move_right():
                    get_sound_thread().play_sfx('Select 6')
            elif 'LEFT' in directions:
                if self.info_graph.move_left():
                    get_sound_thread().play_sfx('Select 6')
            elif 'UP' in directions:
                if self.info_graph.move_up():
                    get_sound_thread().play_sfx('Select 6')
            elif 'DOWN' in directions:
                if self.info_graph.move_down():
                    get_sound_thread().play_sfx('Select 6')

        elif not self.transition:  # Only takes input when not transitioning
            if event == 'INFO':
                get_sound_thread().play_sfx('Info In')
                self.info_graph.set_transition_in()
                self.info_flag = True
                return
            elif event == 'AUX':
                if self.state == 'personal_data' and self.unit.team == 'player' and DB.constants.value('growth_info'):
                    get_sound_thread().play_sfx('Select 3')
                    self.growth_flag = not self.growth_flag
                    if self.growth_flag:
                        self.info_graph.set_current_state('growths')
                    else:
                        self.info_graph.set_current_state('personal_data')
            elif event == 'BACK':
                self.back()
                return
            elif event == 'SELECT':
                mouse_position = get_input_manager().get_mouse_position()
                if mouse_position:
                    mouse_x, mouse_y = mouse_position
                    if mouse_y <= 16:
                        self.move_up()
                    elif mouse_y >= WINHEIGHT - 16:
                        self.move_down()
                if not self.transition:  # Some of the above move commands could cause transition
                    if self.unit.traveler:
                        self.move_traveler_down()
            
            if 'DOWN' in directions:
                self.move_down()
            elif 'UP' in directions:
                self.move_up()

    def move_down(self):
        get_sound_thread().play_sfx('Status_Character')
        if self.rescuer:
            index = self.scroll_units.index(self.rescuer)
            self.rescuer = None
        elif len(self.scroll_units) > 1:
            #If this unit has rescued someone, go to their traveler when pressing down
            if self.unit.traveler:
                self.move_traveler_down()
                return
            index = self.scroll_units.index(self.unit)
        else:
            return
        new_index = (index + 1) % len(self.scroll_units)
        self.next_unit = self.scroll_units[new_index]
        self.transition = 'UP'

    def move_up(self):
        get_sound_thread().play_sfx('Status_Character')
        if self.rescuer:
            new_index = self.scroll_units.index(self.rescuer)
            self.rescuer = None
            self.next_unit = self.scroll_units[new_index]
        elif len(self.scroll_units) > 1:
            index = self.scroll_units.index(self.unit)
            new_index = (index - 1) % len(self.scroll_units)
            self.next_unit = self.scroll_units[new_index]
            #If the unit we are going to has rescued someone, go to their traveler instead when pressing up
            if self.next_unit.traveler:
                self.move_traveler_up()
                return
        else:
            return
        self.transition = 'DOWN'

    def move_traveler_down(self):
        get_sound_thread().play_sfx('Status_Character')
        self.rescuer = self.unit
        self.next_unit = game.get_unit(self.unit.traveler)
        self.transition = 'UP'

    def move_traveler_up(self):
        get_sound_thread().play_sfx('Status_Character')
        self.rescuer = self.next_unit
        self.next_unit = game.get_unit(self.next_unit.traveler)
        self.transition = 'DOWN'

    def handle_mouse(self):
        mouse_position = get_input_manager().get_mouse_position()
        if not mouse_position:
            return
        if self.info_flag:
            self.info_graph.handle_mouse(mouse_position)

    def update(self):
        # Up and Down
        if self.next_unit:
            self.transition_counter += 1
            # Transition in
            if self.next_unit == self.unit:
                if self.transition_counter == 1:
                    self.transparency = .75
                    self.scroll_offset_y = -80 if self.transition == 'DOWN' else 80
                elif self.transition_counter == 2:
                    self.transparency = .6
                    self.scroll_offset_y = -32 if self.transition == 'DOWN' else 32
                elif self.transition_counter == 3:
                    self.transparency = .48
                    self.scroll_offset_y = -16 if self.transition == 'DOWN' else 16
                elif self.transition_counter == 4:
                    self.transparency = .15
                    self.scroll_offset_y = -4 if self.transition == 'DOWN' else 4
                elif self.transition_counter == 5:
                    self.scroll_offset_y = 0
                else:
                    self.transition = None
                    self.transparency = 0
                    self.next_unit = None
                    self.transition_counter = 0
            # Transition out
            else:
                if self.transition_counter == 1:
                    self.transparency = .15
                elif self.transition_counter == 2:
                    self.transparency = .48
                elif self.transition_counter == 3:
                    self.transparency = .6
                    self.scroll_offset_y = 8 if self.transition == 'DOWN' else -8
                elif self.transition_counter == 4:
                    self.transparency = .75
                    self.scroll_offset_y = 16 if self.transition == 'DOWN' else -16
                elif self.transition_counter < 8: # (5, 6, 7, 8):  # Pause for a bit
                    self.transparency = 1.
                    self.scroll_offset_y = 160 if self.transition == 'DOWN' else -160
                else:
                    self.unit = self.next_unit  # Now transition in
                    self.reset_surfs(keep_last_info_graph_aabb=True)

                    self.transition_counter = 0

    def draw(self, surf):
        if self.bg:
            self.bg.draw(surf)
        else:
            # info menu shouldn't be transparent
            surf.blit(SPRITES.get('bg_black'), (0, 0))

        # Image flashy thing at the top of the InfoMenu
        num_frames = 8
        # 8 frames long, 8 different frames
        blend_perc = abs(num_frames - ((engine.get_time()/134) % (num_frames * 2))) / float(num_frames)
        sprite = SPRITES.get('info_menu_flash')
        im = image_mods.make_translucent_blend(sprite, 128. * blend_perc)
        surf.blit(im, (147, 0), None, engine.BLEND_RGB_ADD)

        self.draw_slide(surf)
        self.draw_portrait(surf)

        if self.info_graph.current_bb:
            self.info_graph.draw(surf)

        if not self.transition:
            self.mouse_indicator.draw(surf)

        return surf

    #TO-DO: figure out what I'm going to do with generic portraits
    def draw_portrait(self, surf):
        # Only create if we don't have one in memory
        if not self.portrait_surf:
            self.portrait_surf = self.create_portrait_section()
        portrait_surf = self.portrait_surf.copy()

        # If no portrait for this unit, either create one or default to class card using icons.get_portrait
        if not self.current_portrait:
            portrait = RESOURCES.portraits.get(self.unit.portrait_nid)
            if portrait:
                self.current_portrait = InfoMenuPortrait(portrait, DB.constants.value('info_menu_blink'))
            else:
                im, offset = icons.get_portrait(self.unit)
        # We do have a portrait, so update...
        if self.current_portrait:
            self.current_portrait.update()
            im = self.current_portrait.create_image()
            offset = self.current_portrait.portrait.info_offset
        # Draw portrait onto the portrait surf
        if im:
            x_pos = (im.get_width() - 142)//2
            im_surf = engine.subsurface(im, (x_pos, offset, 139, 144))
            portrait_surf.blit(im_surf, (-4, 16))

        # Stick it on the surface
        if self.transparency:
            im = image_mods.make_translucent(portrait_surf, self.transparency)
            surf.blit(im, (4, self.scroll_offset_y))
        else:
            surf.blit(portrait_surf, (4, self.scroll_offset_y))
        
        #Add the frame. This should not be altered by transitioning up or down
        surf.blit(SPRITES.get('portrait_frame'), (2,3))
        
        # Blit the unit's active/focus map sprite
        if not self.transparency:
            active_sprite = self.unit.sprite.create_image('active')
            x_pos = 121 - active_sprite.get_width()//2
            y_pos = WINHEIGHT - 133
            surf.blit(active_sprite, (x_pos, y_pos + self.scroll_offset_y))
        
        # Draw weapon stats. We're doing it in here because the game won't allow us to draw in this position if we do this elsewhere
        # Only create if we don't have one in memory
        if not self.weapon_stat_surf:
            self.weapon_stat_surf = self.create_equipment_section()
        weapon_stat_surf = self.weapon_stat_surf.copy()
        
        # Stick it on the surface
        if self.transparency:
            im = image_mods.make_translucent(weapon_stat_surf, self.transparency)
            surf.blit(im, (0, self.scroll_offset_y + 245))
        else:
            surf.blit(weapon_stat_surf, (0, self.scroll_offset_y + 245))

    def growth_colors(self, value):
        color = 'yellow'
        if value >= 0 and value <= 20:
            color = 'red-orange'
        elif value > 20 and value <= 30:
            color = 'light-red'
        elif value > 30 and value <= 40:
            color = 'pink-orange'
        elif value > 40 and value <= 50:
            color = 'light-orange'
        elif value > 50 and value <= 60:
            color = 'corn-yellow'
        elif value > 60 and value <= 70:
            color = 'light-green'
        elif value > 70 and value <= 80:
            color = 'olive-green'
        elif value > 80 and value <= 90:
            color = 'soft-green'
        else:  # > 90
            color = 'yellow-green'
        return color

    def create_portrait_section(self):
        surf = engine.create_surface((147, WINHEIGHT), transparent=True)
        surf.blit(SPRITES.get('info_unit'), (8, 205))

        render_text(surf, ['text_big'], [self.unit.name], ['white'], (67, 159), HAlignment.CENTER)
        unit_desc = text_funcs.translate_and_text_evaluate(self.unit.desc, self=self.unit, unit=self.unit)
        self.info_graph.register((52, 159, 84, 24), unit_desc, 'all')
        class_obj = DB.classes.get(self.unit.klass)
        render_text(surf, ['text_big'], [class_obj.name], ['white'], (8, 182))
        class_desc = text_funcs.translate_and_text_evaluate(class_obj.desc, self=class_obj, unit=self.unit)
        self.info_graph.register((8, 182, 128, 16), class_desc, 'all')
        render_text(surf, ['text_big'], [str(self.unit.level)], ['blue'], (52, 202), HAlignment.RIGHT)
        desc = text_funcs.translate_and_text_evaluate('Level_desc', unit=self.unit)
        self.info_graph.register((14, 202, 23, 16), desc, 'all')
        render_text(surf, ['text_big'], [str(self.unit.exp)], ['blue'], (94, 202), HAlignment.RIGHT)
        desc = text_funcs.translate_and_text_evaluate('Exp_desc', unit=self.unit)
        self.info_graph.register((62, 202, 23, 16), desc, 'all')
        
        # Draw HP
        current_hp = str(self.unit.get_hp())
        max_hp = str(self.unit.get_max_hp())
        # 28 pixels is the width of space available to draw current_hp or max_hp
        if text_width('text_big', current_hp) > 21 or text_width('text_big', max_hp) > 21:
            hp_font = 'text'
        else:
            hp_font = 'text_big'
        render_text(surf, [hp_font], [current_hp], ['blue'], (52, 222), HAlignment.RIGHT)
        desc = text_funcs.translate_and_text_evaluate('HP_desc', unit=self.unit)
        self.info_graph.register((14, 222, 62, 16), desc, 'all')
        render_text(surf, [hp_font], [max_hp], ['blue'], (83, 222), HAlignment.RIGHT)

        # Blit the white status platform
        surf.blit(SPRITES.get('status_platform'), (102, 219))
        # Blit affinity
        affinity = DB.affinities.get(self.unit.affinity)
        if affinity:
            icons.draw_item(surf, affinity, (122, 163))
            affinity_desc = text_funcs.translate_and_text_evaluate(affinity.desc, self=affinity, unit=self.unit)
            self.info_graph.register((128, 162, 16, 16), affinity_desc, 'all')
        # Blit leadership stars
        leadership = self.unit.stats['LEAD']
        if leadership:
            lead_desc = text_funcs.translate_and_text_evaluate('Lead_desc', unit=self.unit)
            self.info_graph.register((-1, 163, 16, 16), lead_desc, 'all')
            surf.blit(SPRITES.get('lead_star'), (9, 163))
            render_text(surf, ['text'], [str(leadership)], ['blue'], (2, 163), HAlignment.LEFT)
        return surf

    def create_equipment_section(self):
        surf = engine.create_surface((147, WINHEIGHT - 75), transparent=True)
        weapon = self.unit.get_weapon()
        # Populate battle info
        surf.blit(SPRITES.get('equipment_logo'), (14, 6))
        render_text(surf, ['text_big'], [text_funcs.translate('Rng')], ['yellow'], (76, 2))
        rng_desc = text_funcs.translate_and_text_evaluate('Rng_desc', unit=self.unit)
        self.info_graph.register((78, 252, 56, 16), rng_desc, 'all')
        render_text(surf, ['text_big'], [text_funcs.translate('Atk')], ['yellow'], (9, 25))
        atk_desc = text_funcs.translate_and_text_evaluate('Atk_desc', unit=self.unit)
        self.info_graph.register((11, 275, 64, 16), atk_desc, 'all')
        render_text(surf, ['text_big'], [text_funcs.translate('Hit')], ['yellow'], (9, 48))
        hit_desc = text_funcs.translate_and_text_evaluate('Hit_desc', unit=self.unit)
        self.info_graph.register((11, 298, 64, 16), hit_desc, 'all')
        if DB.constants.value('crit'):
            render_text(surf, ['text_big'], [text_funcs.translate('Crit')], ['yellow'], (76, 25))
            crit_desc = text_funcs.translate_and_text_evaluate('Crit_desc', unit=self.unit)
            self.info_graph.register((78, 275, 56, 16), crit_desc, 'all')
        else:
            render_text(surf, ['text_big'], [text_funcs.translate('AS')], ['yellow'], (76, 25))
            AS_desc = text_funcs.translate_and_text_evaluate('AS_desc', unit=self.unit)
            self.info_graph.register((78, 275, 56, 16), AS_desc, 'all')
        render_text(surf, ['text_big'], [text_funcs.translate('Avd')], ['yellow'], (76, 48))
        avoid_desc = text_funcs.translate_and_text_evaluate('Avoid_desc', unit=self.unit)
        self.info_graph.register((78, 298, 56, 16), avoid_desc, 'all')

        if weapon:
            rng = item_funcs.get_range_string(self.unit, weapon)
            dam = str(combat_calcs.damage(self.unit, weapon))
            acc = str(combat_calcs.accuracy(self.unit, weapon))
            crt = combat_calcs.crit_accuracy(self.unit, weapon)
            if crt is None:
                crt = '--'
            else:
                crt = str(crt)
        else:
            rng, dam, acc, crt = '--', '--', '--', '--'

        render_text(surf, ['text_big'], [rng], ['blue'], (136, 2), HAlignment.RIGHT)
        render_text(surf, ['text_big'], [dam], ['blue'], (65, 25), HAlignment.RIGHT)
        render_text(surf, ['text_big'], [acc], ['blue'], (65, 48), HAlignment.RIGHT)
        if DB.constants.value('crit'):
            render_text(surf, ['text_big'], [crt], ['blue'], (136, 25), HAlignment.RIGHT)
        else:  
            attack_speed = str(combat_calcs.attack_speed(self.unit, weapon))
            render_text(surf, ['text_big'], [attack_speed], ['blue'], (136, 25), HAlignment.RIGHT)
        avo = str(combat_calcs.avoid(self.unit, weapon))
        if int(avo) > -99:
            render_text(surf, ['text_big'], [avo], ['blue'], (136, 48), HAlignment.RIGHT)
        else:
            #If a unit's avoid is less than 0, their ass isn't avoiding anything
            render_text(surf, ['text_big'], ['No'], ['blue'], (136, 48), HAlignment.RIGHT)
        
        return surf

    def draw_slide(self, surf):
        top_surf = engine.create_surface((WINWIDTH, WINHEIGHT), transparent=True)
        main_surf = engine.copy_surface(top_surf)

        # Blit title of menu
        top_surf.blit(SPRITES.get('info_title_background'), (209, 12))
        if self.logo:
            self.logo.update()
            self.logo.draw(top_surf)

        #if self.state == 'personal_data':
        if self.growth_flag:
            if not self.growths_surf:
                self.growths_surf = self.create_personal_data_surf(growths=True)
            self.draw_growths_surf(main_surf)
        else:
            if not self.personal_data_surf:
                self.personal_data_surf = self.create_personal_data_surf()
            self.draw_stat_surf(self.personal_data_surf)
            self.draw_personal_data_surf(main_surf)
        #Skills label
        main_surf.blit(SPRITES.get('skills_logo'), (360, WINHEIGHT - 93))
        if not self.class_skill_surf:
            self.class_skill_surf = self.create_class_skill_surf()
        self.draw_class_skill_surf(main_surf)
        if DB.constants.value('fatigue') and self.unit.team == 'player' and \
                game.game_vars.get('_fatigue'):
            if not self.fatigue_surf:
                self.fatigue_surf = self.create_fatigue_surf()
            self.draw_fatigue_surf(main_surf)

        #elif self.state == 'equipment':
        if not self.equipment_surf:
            self.equipment_surf = self.create_equipment_surf()
        self.draw_equipment_surf(main_surf)

        #elif self.state == 'support_skills':
        main_surf.blit(SPRITES.get('status_logo'), (357, WINHEIGHT - 56))
        if not self.skill_surf:
            self.skill_surf = self.create_skill_surf()
        self.draw_skill_surf(main_surf)
        if not self.wexp_surf:
            self.wexp_surf = self.create_wexp_surf()
        self.draw_wexp_surf(main_surf)
        if not self.support_surf:
            self.support_surf = self.create_support_surf()
        self.draw_support_surf(main_surf)

        if self.state == 'notes':
            if not self.notes_surf:
                self.notes_surf = self.create_notes_surf()
            self.draw_notes_surf(main_surf)

        # Now put it in the right place
        offset_x = max(147, 147 - self.scroll_offset_x)
        main_surf = engine.subsurface(main_surf, (offset_x, 0, main_surf.get_width() - offset_x, WINHEIGHT))
        surf.blit(main_surf, (max(147, 147 + self.scroll_offset_x), self.scroll_offset_y))
        if self.transparency:
            top_surf = image_mods.make_translucent(top_surf, self.transparency)
        surf.blit(top_surf, (0, self.scroll_offset_y)) 

    def draw_stat_surf(self, surf):
        idx = 0
        for i, stat_nid in enumerate(self.left_stats):
            icons.draw_stat(surf, stat_nid, self.unit, (66, 23 * idx + 33))
            idx += 1

        for i, stat_nid in enumerate(self.right_stats):
            #CON basically doesn't exist
            if stat_nid == 'CON':
                continue
            icons.draw_stat(surf, stat_nid, self.unit, (66, 23 * idx + 33))
            idx += 1

    def create_personal_data_surf(self, growths=False):
        if growths:
            state = 'growths'
        else:
            state = 'personal_data'

        menu_size = WINWIDTH - 147, WINHEIGHT
        surf = engine.create_surface(menu_size, transparent=True)
        
        idx = 0
        for i, stat_nid in enumerate(self.left_stats):
            curr_stat = DB.stats.get(stat_nid)

            # Value
            if growths:
                icons.draw_growth(surf, stat_nid, self.unit, (66, 23 * idx + 33))
            else:
                highest_stat = curr_stat.maximum
                max_stat = self.unit.get_stat_cap(stat_nid)
                if max_stat > 0:
                    total_length = int(max_stat / highest_stat * 42) * 2 - 1
                    base_value = self.unit.stats.get(stat_nid, 0)
                    subtle_stat_bonus = self.unit.subtle_stat_bonus(stat_nid)
                    base_value += subtle_stat_bonus
                    frac = utils.clamp(base_value / max_stat, 0, 1)
                    build_groove(surf, (40, 23 * idx + 48), total_length, frac)

            # Name
            name = curr_stat.name
            color = 'yellow'
            if DB.stats.get(stat_nid).growth_colors and self.unit.team == 'player':
                color = self.growth_colors(unit_funcs.growth_rate(self.unit, stat_nid))
            render_text(surf, ['text_big'], [name], [color], (9, 23 * idx + 33))
            if growths:
                contribution = unit_funcs.growth_contribution(self.unit, stat_nid)
            else:
                base_value = self.unit.stats.get(stat_nid, 0)
                subtle_stat_bonus = self.unit.subtle_stat_bonus(stat_nid)
                base_value += subtle_stat_bonus
                contribution = self.unit.stat_contribution(stat_nid)
                contribution['Base Value'] = base_value
            desc_text = text_funcs.translate_and_text_evaluate(curr_stat.desc, self=curr_stat, unit=self.unit)
            help_box = help_menu.StatDialog(desc_text or ('%s_desc' % stat_nid), contribution)
            self.info_graph.register((158, 23 * idx + 33, 64, 24), help_box, 'all', first=(idx == 0))
            idx += 1
        
        for i, stat_nid in enumerate(self.right_stats):
            curr_stat = DB.stats.get(stat_nid)
            #Skip CON since it'll always be 0
            if stat_nid == "CON":
                continue
            
            # Name
            name = curr_stat.name
            color = 'yellow'
            if DB.stats.get(stat_nid).growth_colors and self.unit.team == 'player':
                color = self.growth_colors(unit_funcs.growth_rate(self.unit, stat_nid))
            render_text(surf, ['text_big'], [name], [color], (9, 23 * idx + 33))
            if growths:
                icons.draw_growth(surf, stat_nid, self.unit, (66, 23 * idx + 33))
                contribution = unit_funcs.growth_contribution(self.unit, stat_nid)
            else:
                base_value = self.unit.stats.get(stat_nid, 0)
                subtle_stat_bonus = self.unit.subtle_stat_bonus(stat_nid)
                base_value += subtle_stat_bonus
                contribution = self.unit.stat_contribution(stat_nid)
                contribution['Base Value'] = base_value
            desc_text = text_funcs.translate_and_text_evaluate(curr_stat.desc, self=curr_stat, unit=self.unit)
            help_box = help_menu.StatDialog(desc_text or ('%s_desc' % stat_nid), contribution)
            self.info_graph.register((158, 23 * idx + 33, 64, 16), help_box, 'all')
            idx += 1
        
        other_stats = []
        #if DB.constants.value('enable_rating'):
        #    other_stats.append('RAT')
        if DB.constants.value('pairup') and DB.constants.value('attack_stance_only'):
            pass
        else:
            #other_stats.append('AID') #Like CON, we don't display AID
            other_stats.append('TRV')
        if self.unit.get_max_mana() > 0:
            other_stats.append('MANA')
        if DB.constants.value('pairup') and not DB.constants.value('attack_stance_only'):
            other_stats.append('GAUGE')
        #if DB.constants.value('lead'): #We draw Leadership stars elsewhere
        #    other_stats.append('LEAD')
        if DB.constants.value('talk_display'):
            other_stats.append('TALK')
        other_stats.append('FUNDS')
        
        #Only non-generic units can have lovers and influences
        if self.unit.nid in DB.units:
            other_stats.append('LOVER') #LOVER handles both since the game refuses to check for "INFLUENCE" for some reason
        
        other_stats = other_stats[:6 - len(self.right_stats)]

        for i, stat in enumerate(other_stats):
            true_idx = idx #Only here so the stats we don't care about don't produce errors

            if stat == 'TRV' and self.unit.traveler:
                trav = game.get_unit(self.unit.traveler)
                render_text(surf, ['text_big'], [trav.name], ['blue'], (43, 23 * idx + 33))
                render_text(surf, ['text_big'], [text_funcs.translate('Trv')], ['yellow'], (9, 23 * idx + 33))
                desc = text_funcs.translate_and_text_evaluate('Trv_desc', unit=self.unit)
                self.info_graph.register((158, 23 * idx + 33, 64, 16), desc, 'all')
            
            #I only updated TRV and TALK, in addition to adding FUNDS. If you're using this engine you're on your own for the rest
            elif stat == 'AID':
                if growths:
                    icons.draw_growth(surf, 'HP', self.unit, (111, 16 * true_idx + 24))
                    color = 'yellow'
                    if DB.stats.get('HP').growth_colors and self.unit.team == 'player':
                        color = self.growth_colors(unit_funcs.growth_rate(self.unit, 'HP'))
                    render_text(surf, ['text'], [text_funcs.translate('HP')], [color], (72, 16 * true_idx + 24))
                    desc = text_funcs.translate_and_text_evaluate('HP_desc', unit=self.unit)
                    self.info_graph.register((96 + 72, 16 * true_idx + 24, 64, 16), desc, state)
                else:
                    aid = equations.parser.rescue_aid(self.unit)
                    render_text(surf, ['text'], [str(aid)], ['blue'], (111, 16 * true_idx + 24), HAlignment.RIGHT)

                    # Mount Symbols
                    for tag in self.unit.tags:
                        if ('aid_icon_%s' % tag) in SPRITES:
                            aid_surf = SPRITES.get('aid_icon_%s' % tag)
                            break
                    else:
                        if 'Dragon' in self.unit.tags:
                            aid_surf = engine.subsurface(SPRITES.get('aid_icons'), (0, 48, 16, 16))
                        elif 'Flying' in self.unit.tags:
                            aid_surf = engine.subsurface(SPRITES.get('aid_icons'), (0, 32, 16, 16))
                        elif 'Mounted' in self.unit.tags:
                            aid_surf = engine.subsurface(SPRITES.get('aid_icons'), (0, 16, 16, 16))
                        else:
                            aid_surf = engine.subsurface(SPRITES.get('aid_icons'), (0, 0, 16, 16))
                    surf.blit(aid_surf, (112, 16 * true_idx + 24))
                    render_text(surf, ['text'], [text_funcs.translate('Aid')], ['yellow'], (72, 16 * true_idx + 24))
                    desc = text_funcs.translate_and_text_evaluate('Aid_desc', unit=self.unit)
                    self.info_graph.register((96 + 72, 16 * true_idx + 24, 64, 16), desc, state)

            elif stat == 'RAT':
                rat = str(equations.parser.rating(self.unit))
                render_text(surf, ['text'], [rat], ['blue'], (111, 16 * true_idx + 24), HAlignment.RIGHT)
                render_text(surf, ['text'], [text_funcs.translate('Rat')], ['yellow'], (72, 16 * true_idx + 24))
                desc = text_funcs.translate_and_text_evaluate('Rating_desc', unit=self.unit)
                self.info_graph.register((96 + 72, 16 * true_idx + 24, 64, 16), desc, state)

            elif stat == 'MANA':
                mana = str(self.unit.current_mana)
                render_text(surf, ['text'], [mana], ['blue'], (111, 16 * true_idx + 24), HAlignment.RIGHT)
                render_text(surf, ['text'], [text_funcs.translate('MANA')], ['yellow'], (72, 16 * true_idx + 24))
                desc = text_funcs.translate_and_text_evaluate('MANA_desc', unit=self.unit)
                self.info_graph.register((96 + 72, 16 * true_idx + 24, 64, 16), desc, state)

            elif stat == 'GAUGE':
                gge = str(self.unit.get_guard_gauge())
                render_text(surf, ['text'], [gge], ['blue'], (111, 16 * true_idx + 24), HAlignment.RIGHT)
                render_text(surf, ['text'], [text_funcs.translate('GAUGE')], ['yellow'], (72, 16 * true_idx + 24))
                desc = text_funcs.translate_and_text_evaluate('GAUGE_desc', unit=self.unit)
                self.info_graph.register((96 + 72, 16 * true_idx + 24, 64, 16), desc, state)
            
            elif stat == 'TALK':
                if (len([talk for talk in game.talk_options if talk[0] == self.unit.nid and talk not in game.talk_hidden]) != 0):
                    talkee = [talk for talk in game.talk_options if talk[0] == self.unit.nid][0][1]
                    render_text(surf, ['text_big'], [game.get_unit(talkee).name], ['blue'], (43, 23 * idx + 33))
                else:
                    render_text(surf, ['text_big'], ['--'], ['blue'], (59, 23 * idx + 33), HAlignment.RIGHT)
                render_text(surf, ['text_big'], [text_funcs.translate('Talk')], ['yellow'], (9, 23 * idx + 33))
                desc = text_funcs.translate_and_text_evaluate('Talk_desc', unit=self.unit)
                self.info_graph.register((158, 23 * idx + 33, 64, 16), desc, 'all')
            
            elif stat == 'FUNDS':
                render_text(surf, ['text_big'], [str(self.unit.personal_funds)], ['blue'], (56, 23 * idx + 33))
                render_text(surf, ['text_big'], [text_funcs.translate('Funds')], ['yellow'], (9, 23 * idx + 33))
                desc = text_funcs.translate_and_text_evaluate('Pfunds_desc', unit=self.unit)
                self.info_graph.register((158, 23 * idx + 33, 64, 16), desc, 'all')
            
            #LEAD shouldn't ever actually be able to run
            elif stat == 'LEAD':
                render_text(surf, ['text'], [text_funcs.translate('Lead')], ['yellow'], (72, 16 * true_idx + 24))
                desc = text_funcs.translate_and_text_evaluate('Lead_desc', unit=self.unit)
                self.info_graph.register((96 + 72, 16 * true_idx + 24, 64, 16), desc, state)

                if growths:
                    icons.draw_growth(surf, 'LEAD', self.unit, (111, 16 * true_idx + 24))
                else:
                    icons.draw_stat(surf, 'LEAD', self.unit, (111, 16 * true_idx + 24))
                    lead_surf = engine.subsurface(SPRITES.get('lead_star'), (0, 0, 16, 16))
                    surf.blit(lead_surf, (111, 16 * true_idx + 24))
            
            elif stat == 'LOVER':
                #Lover
                #render_text(surf, ['text_big'], [str(self.unit.personal_funds)], ['blue'], (56, 23 * idx + 33))
                render_text(surf, ['text_big'], ['--'], ['blue'], (75, 23 * idx + 33), HAlignment.RIGHT)
                render_text(surf, ['text_big'], [text_funcs.translate('Lover')], ['yellow'], (9, 23 * idx + 33))
                
                #Influence
                #render_text(surf, ['text_big'], [str(self.unit.personal_funds)], ['blue'], (56, 23 * idx + 33))
                render_text(surf, ['text_big'], ['--'], ['blue'], (101, 23 * (idx + 1) + 33), HAlignment.RIGHT)
                render_text(surf, ['text_big'], [text_funcs.translate('Influence')], ['yellow'], (9, 23 * (idx + 1) + 33))
                idx += 1
            
            idx += 1
        
        return surf

    def draw_personal_data_surf(self, surf):
        surf.blit(self.personal_data_surf, (147, 0))

    def draw_growths_surf(self, surf):
        surf.blit(self.growths_surf, (147, 0))

    def create_wexp_surf(self):
        wexp_to_draw: List[Tuple[str, int]] = []
        for weapon, wexp in self.unit.wexp.items():
            if wexp > 0 and weapon in unit_funcs.usable_wtypes(self.unit) \
                and weapon in DB.weapons.get_visible_weapon_types():
                wexp_to_draw.append((weapon, wexp))
        width = (WINWIDTH - 102) // 2

        surf = engine.create_surface((WINWIDTH - 424, WINHEIGHT - 34), transparent=True)
        if not wexp_to_draw:
            return surf
        counter = 0
        for y in range(0, 32, 16):
            for x in range(0, 2):
                weapon, value = wexp_to_draw[counter]
                weapon_rank = DB.weapon_ranks.get_rank_from_wexp(value)
                next_weapon_rank = DB.weapon_ranks.get_next_rank_from_wexp(value)
                
                # Get the vertical offset
                offset = counter * 25
                # Draw a big icon from the engine's sprite folder instead of a normal weapon icon
                icons.draw_big_weapon(surf, weapon, (0, offset + 1))

                # Add text
                pos = (30, offset)
                if FONT.get('rank_big'):
                    render_text(surf, ['rank_big'], [weapon_rank.nid], ['blue'], pos, HAlignment.CENTER)
                elif FONT.get('text_big'):
                    render_text(surf, ['text_big'], [weapon_rank.nid], ['blue'], pos, HAlignment.CENTER)
                elif FONT.get('rank'):
                    render_text(surf, ['rank'], [weapon_rank.nid], ['blue'], pos, HAlignment.CENTER)
                else:
                    render_text(surf, ['text'], [weapon_rank.nid], ['blue'], pos, HAlignment.CENTER)
                self.info_graph.register((426, 36 + pos[1], width, 16), "%s mastery level: %d" % (DB.weapons.get(weapon).name, value), 'all', first=(counter==0))
                counter += 1
                if counter >= len(wexp_to_draw):
                    break
            if counter >= len(wexp_to_draw):
                break

        return surf

    def draw_wexp_surf(self, surf):
        surf.blit(self.wexp_surf, (424, 34))

    def create_equipment_surf(self):
        def create_item_option(idx, item):
            return BasicItemOption.from_item(idx, item, width=136, font="text_big", mode=ItemOptionModes.USES, text_color=item_system.text_color(None, item))

        #surf = engine.create_surface((WINWIDTH - 270, WINHEIGHT - 9), transparent=True)
        surf = engine.create_surface((WINWIDTH, WINHEIGHT), transparent=True)
        item_surf = engine.create_surface((WINWIDTH - 270, WINHEIGHT - 9), transparent=True)
        
        weapon = self.unit.get_weapon()
        accessory = self.unit.get_accessory()

        # Blit items
        for idx, item in enumerate(self.unit.nonaccessories):
            equipped_subitem: Optional[ItemObject] = None
            if item.multi_item and any(subitem is weapon for subitem in item.subitems):
                item_surf.blit(SPRITES.get('equipment_highlight_big'), (8, idx * 23 + 35))
                for subitem in item.subitems:
                    if subitem is weapon:
                        equipped_subitem = subitem
                        item_option = create_item_option(idx, subitem)
                        break
                else:  # Shouldn't happen
                    item_option = create_item_option(idx, item)
            else:
                if item is weapon:
                    item_surf.blit(SPRITES.get('equipment_highlight_big'), (8, idx * 23 + 35))
                item_option = create_item_option(idx, item)
            item_option.draw(item_surf, 8, idx * 23 + 24)
            help_dlg = build_dialog_list(equipped_subitem if equipped_subitem else item, PageType.ITEM, unit=self.unit)
            self.info_graph.register((282, idx * 23 + 35, 120, 16), help_dlg, 'all', first=(idx == 0))
        
        surf.blit(item_surf, (270, 9))
        
        #We don't have accessories.
        '''
        # Blit accessories
        for idx, item in enumerate(self.unit.accessories):
            aidx = item_funcs.get_num_items(self.unit) + idx
            y_pos = aidx * 16 + 24
            equipped_subitem: Optional[ItemObject] = None
            if item.multi_item and any(subitem is accessory for subitem in item.subitems):
                surf.blit(SPRITES.get('equipment_highlight'), (8, y_pos + 8))
                for subitem in item.subitems:
                    if subitem is accessory:
                        equipped_subitem = subitem
                        item_option = create_item_option(aidx, subitem)
                        break
                else:  # Shouldn't happen
                    item_option = create_item_option(aidx, item)
            else:
                if item is accessory:
                    surf.blit(SPRITES.get('equipment_highlight'), (8, y_pos + 8))
                item_option = create_item_option(aidx, item)
            item_option.draw(surf, 8, y_pos)
            first = (idx == 0 and not self.unit.nonaccessories)
            help_dlg = build_dialog_list(equipped_subitem if equipped_subitem else item, PageType.ITEM, unit=self.unit)
            self.info_graph.register((147 + 8, y_pos, 120, 16), help_dlg, 'equipment', first=first)
        '''
        
        #Moved the battle stats to draw_portrait and create_equipment_section, as it wouldn't draw properly if coded here
        return surf

    def draw_equipment_surf(self, surf):
        surf.blit(self.equipment_surf, (0,0))

    def create_skill_surf(self):
        surf = engine.create_surface((WINWIDTH - 285, 48), transparent=True)
        skills = [skill for skill in self.unit.skills if not (skill.class_skill or skill_system.hidden(skill, self.unit))]
        # stacked skills appear multiple times, but should be drawn only once
        skill_counter = {}
        unique_skills = []
        for skill in skills:
            if skill.nid not in skill_counter:
                skill_counter[skill.nid] = 1
                unique_skills.append(skill)
            else:
                skill_counter[skill.nid] += 1
        for idx, skill in enumerate(unique_skills[:14]):
            if idx <= 6:
                left_pos = idx * 24
                top_pos = 4
            else:
                left_pos = (idx - 7) * 24
                top_pos = 20
            
            icons.draw_skill(surf, skill, (left_pos + 8, top_pos), compact=False, grey=skill_system.is_grey(skill, self.unit))
            if skill_counter[skill.nid] > 1:
                text = str(skill_counter[skill.nid])
                render_text(surf, ['small'], [text], ['white'], (left_pos + 20 - 4 * len(text), top_pos + 2))
            text = text_funcs.translate_and_text_evaluate(
                skill.desc,
                unit=game.get_unit(skill.owner_nid),
                self=skill)
            help_dlg = build_dialog_list(skill, PageType.SKILL, unit=self.unit)
            self.info_graph.register((285 + left_pos + 8, WINHEIGHT - 48 + top_pos, 16, 16), help_dlg, 'all')

        return surf

    def draw_skill_surf(self, surf):
        surf.blit(self.skill_surf, (285, WINHEIGHT - 48))

    def create_class_skill_surf(self):
        surf = engine.create_surface((WINWIDTH - 285, 24), transparent=True)
        class_skills = [skill for skill in self.unit.skills if skill.class_skill and not skill_system.hidden(skill, self.unit)]

        # stacked skills appear multiple times, but should be drawn only once
        skill_counter = {}
        unique_skills = list()
        for skill in class_skills:
            if skill.nid not in skill_counter:
                skill_counter[skill.nid] = 1
                unique_skills.append(skill)
            else:
                skill_counter[skill.nid] += 1
        for idx, skill in enumerate(unique_skills[:6]):
            left_pos = idx * 24
            icons.draw_skill(surf, skill, (left_pos + 8, 8), compact=False, grey=skill_system.is_grey(skill, self.unit))
            if skill_counter[skill.nid] > 1:
                text = str(skill_counter[skill.nid])
                render_text(surf, ['small'], [text], ['white'], (left_pos + 20 - 4 * len(text), 6))
            text = text_funcs.translate_and_text_evaluate(
                skill.desc,
                unit=game.get_unit(skill.owner_nid),
                self=skill)
            help_dlg = build_dialog_list(skill, PageType.SKILL, unit=self.unit)
            if self._extra_stat_row:
                self.info_graph.register((285 + left_pos + 8, WINHEIGHT - 70, 16, 16), help_dlg, 'all')
            else:
                self.info_graph.register((285 + left_pos + 8, WINHEIGHT - 80, 16, 16), help_dlg, 'all')

        return surf

    def draw_class_skill_surf(self, surf):
        if self._extra_stat_row:
            surf.blit(self.class_skill_surf, (285, WINHEIGHT - 88))
        else:
            surf.blit(self.class_skill_surf, (285, WINHEIGHT - 88))

    def create_support_surf(self):
        surf = engine.create_surface((WINWIDTH - 147, WINHEIGHT), transparent=True)
        width = (WINWIDTH - 102) // 2

        if game.game_vars.get('_supports'):
            pairs = game.supports.get_pairs(self.unit.nid)
            pairs = [pair for pair in pairs if pair.unlocked_ranks]
        else:
            pairs = []

        pairs = pairs[:6] # max six supports displayed

        top = self.wexp_surf.get_height() + 24
        for idx, pair in enumerate(pairs):
            x, y = (idx) % 2, idx // 2
            other_unit = None
            if pair.unit1 == self.unit.nid:
                other_unit = game.get_unit(pair.unit2)
            elif pair.unit2 == self.unit.nid:
                other_unit = game.get_unit(pair.unit1)
            if not other_unit:
                continue
            affinity = DB.affinities.get(other_unit.affinity)
            if affinity:
                icons.draw_item(surf, affinity, (x * width + 8, y * 16 + top))
                affinity_desc = text_funcs.translate_and_text_evaluate(affinity.desc, unit=self.unit)
                self.info_graph.register((147 + x * width + 8, y * 16 + top, WINWIDTH - 120, 16), affinity_desc, 'support_skills')
            render_text(surf, ['narrow'], [other_unit.name], [], (x * width + 22, y * 16 + top))
            highest_rank = pair.unlocked_ranks[-1]
            render_text(surf, ['text'], [highest_rank], ['yellow'], (x * width + surf.get_width()/2 - 2, y * 16 + top), HAlignment.RIGHT)
        return surf

    def draw_support_surf(self, surf):
        surf.blit(self.support_surf, (147, 0))

    def create_fatigue_surf(self):
        surf = engine.create_surface((WINWIDTH - 147, WINHEIGHT), transparent=True)
        max_fatigue = max(1, self.unit.get_max_fatigue())
        fatigue = self.unit.get_fatigue()
        build_groove(surf, (27, WINHEIGHT - 9), 88, utils.clamp(fatigue / max_fatigue, 0, 1))
        x_pos = 27 + 88 // 2
        text = str(fatigue) + '/' + str(max_fatigue)
        x_pos -= text_width('text', text)//2
        render_text(surf, ['text'], [text], ['blue'], (x_pos, WINHEIGHT - 17))
        if fatigue >= max_fatigue:
            render_text(surf, ['text'], [str(fatigue)], ['red'], (x_pos, WINHEIGHT - 17))
        render_text(surf, ['text'], [text_funcs.translate('Ftg')], ['yellow'], (8, WINHEIGHT - 17))

        return surf

    def draw_fatigue_surf(self, surf):
        surf.blit(self.fatigue_surf, (147, 0))

    def create_notes_surf(self):
        # Menu background
        menu_surf = engine.create_surface((WINWIDTH - 147, WINHEIGHT), transparent=True)

        text_parser = TextEvaluator(logging.getLogger(), game, self.unit)
        my_notes = self.unit.notes

        if my_notes:
            total_height = 24
            help_offset = 0
            for idx, note in enumerate(my_notes):
                category = note[0]
                entries = note[1].split(',')
                render_text(menu_surf, ['text'], [category], ['blue'], (10, total_height))
                for entry in entries:
                    category_length = text_width('text', category)
                    left_pos = 64 if category_length <= 64 else (category_length + 8)
                    render_text(menu_surf, ['text'], [text_parser._evaluate_all(entry)], [], (left_pos, total_height))
                    total_height += 16
                self.info_graph.register((147, 16 * help_offset + 24, 64, 16), '%s_desc' % category, 'notes', first=(idx == 0))
                help_offset += len(entries)

        return menu_surf

    def draw_notes_surf(self, surf):
        surf.blit(self.notes_surf, (147, 0))
