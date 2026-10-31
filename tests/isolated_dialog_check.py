"""Former-dialog regression entry: output/PSR forms now live only on the left."""
from pathlib import Path
import sys
from tkinter import ttk
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from inline_output_check import InlineTestCase, main


class IsolatedInlineWorkflowChecks(InlineTestCase):
    def test_output_and_psr_navigation_do_not_create_dialogs(self):
        with patch('isolated_ui.tk.Toplevel') as dialog:
            output_frame=self.app.edit_outputs()
            self.app.feedback_mode.set('PSR-MP6005')
            psr_frame=self.app.edit_psr()
        dialog.assert_not_called()
        self.assertIs(output_frame,self.app._param_sections['spec'])
        self.assertIs(psr_frame,self.app._param_sections['ctrl'])

    def test_no_config_controls_duplicated_in_right_notebook(self):
        def walk(widget):
            for child in widget.winfo_children():
                yield child
                yield from walk(child)
        editable=(ttk.Entry,ttk.Checkbutton,ttk.Combobox,ttk.Spinbox)
        self.assertFalse(any(isinstance(widget,editable) for widget in walk(self.app.tab_topology)))
        self.assertIs(self.app.feedback_pick.master,self.app._param_sections['ctrl'])

    def test_flyback_has_rectifiers_caps_and_windings_but_no_chokes(self):
        self.outputs(2)
        for rail in (1,2):
            for key in ('V_out','P_out','Vf_diode','Qrr','C_out','Rc','ESL','Ns','d_wire_s','n_strand_s'):
                self.assertTrue(self.shown(rail,key),f'OUT{rail}.{key}')
            self.assertFalse(self.shown(rail,'Rd_diode'))
            self.assertFalse(self.shown(rail,'L'))
            self.assertFalse(self.shown(rail,'core_choice_L'))
        self.assertFalse(self.shown(3,'V_out'))

    def test_only_forward_has_chokes_and_shared_rectifier_notice(self):
        self.outputs(2)
        self.app.params['topology'].set(main.TOPO_LABEL['ACF-FORWARD'])
        self.app._filter_params()
        for rail in (1,2):
            self.assertTrue(self.shown(rail,'L'))
            self.assertTrue(self.shown(rail,'core_choice_L'))
            heading=self.app._inline_output_widgets[rail-1,'_rectifier_heading'][0]
            self.assertIn('共用参数',heading.cget('text'))
        self.app.params['topology'].set(main.TOPO_LABEL['QR-FLYBACK'])
        self.assertFalse(self.shown(1,'L'))
        self.assertFalse(self.shown(1,'core_choice_L'))

    def test_nonisolated_hides_multioutput_configuration(self):
        self.outputs(6)
        for topology in ('BUCK','BOOST','BUCK-BOOST'):
            self.app.params['topology'].set(main.TOPO_LABEL[topology])
            self.app._filter_params()
            self.assertFalse(self.app._inline_multi_check.grid_info())
            for rail in range(1,7):
                self.assertFalse(self.shown(rail,'V_out'))
                self.assertFalse(self.shown(rail,'Ns'))

    def test_optional_devices_only_appear_when_enabled(self):
        self.outputs(1)
        self.set_output(1,'cout2_enable',False)
        self.set_output(1,'d_out_enable',False)
        self.app._filter_params()
        self.assertFalse(self.shown(1,'C_out2'))
        self.assertFalse(self.shown(1,'Vf_dout'))
        self.set_output(1,'cout2_enable',True)
        self.set_output(1,'d_out_enable',True)
        self.assertTrue(self.shown(1,'C_out2'))
        self.assertTrue(self.shown(1,'Vf_dout'))

    def test_psr_fields_only_in_fixed_flyback_psr(self):
        widget=self.app._inline_psr_widgets['psr_Rcomp'][1]
        self.assertFalse(widget.grid_info())
        self.app.feedback_mode.set('PSR-MP6005')
        self.assertTrue(widget.grid_info())
        self.app.params['topology'].set(main.TOPO_LABEL['QR-FLYBACK'])
        self.assertFalse(widget.grid_info())
        self.app.params['topology'].set(main.TOPO_LABEL['FLYBACK'])
        self.assertTrue(widget.grid_info())

    def test_search_out_number_and_capacitor_does_not_reveal_unrelated_fields(self):
        self.outputs(6)
        self.app.param_search.set('out2')
        self.app._filter_params()
        self.assertTrue(self.shown(2,'V_out'))
        self.assertFalse(self.shown(1,'V_out'))
        self.assertFalse(self.shown(2,'L'))
        self.app.param_search.set('电容')
        self.app._filter_params()
        self.assertTrue(self.shown(2,'C_out'))
        self.assertFalse(self.shown(2,'Vf_diode'))
        self.assertFalse(self.shown(2,'Ns'))

    def test_folded_sections_reclaim_real_height(self):
        self.outputs(6)
        frame=self.app._param_sections['capacitors']
        self.root.update()
        expanded=frame._section_container.winfo_height()
        self.app._folded_sections.add(frame)
        self.app._filter_params()
        self.root.update()
        collapsed=frame._section_container.winfo_height()
        self.assertLess(collapsed,expanded/3)
        self.assertFalse(frame.winfo_ismapped())
        self.app._folded_sections.discard(frame)
        self.app._filter_params()
        self.root.update()
        self.assertGreater(frame._section_container.winfo_height(),collapsed*3)

    def test_result_subpages_hide_even_if_selected(self):
        book=self.app._isolated_result_book
        diagram,output,psr=self.app._isolated_result_pages
        self.assertEqual(str(book.tab(output,'state')),'hidden')
        self.assertEqual(str(book.tab(psr,'state')),'hidden')
        self.outputs(2)
        self.assertEqual(str(book.tab(output,'state')),'normal')
        book.select(output)
        self.app.multi_enabled.set(False)
        self.assertEqual(book.select(),str(diagram))
        self.app.feedback_mode.set('PSR-MP6005')
        self.assertEqual(str(book.tab(psr,'state')),'normal')
        book.select(psr)
        self.app.params['topology'].set(main.TOPO_LABEL['QR-FLYBACK'])
        self.assertEqual(str(book.tab(psr,'state')),'hidden')
        self.assertEqual(book.select(),str(diagram))


if __name__=='__main__': unittest.main(verbosity=2)
