#!/usr/bin/env python
"""MCP server exposing the switching-power-supply design engine to AI clients.

Transport: stdio.  Configure in your AI client (ZCode example):

    {
      "mcpServers": {
        "psu-designer": {
          "command": "python",
          "args": ["<project-root>/mcp_server.py"]
        }
      }
    }

Tools (all take/return JSON strings):
    run_design(spec)        full design report + machine-readable checks
    run_corners(spec)       Vin-min/max × load grid, worst-case summary
    load_transient(spec,di) load-step ΔV estimate (ESR + capacitive terms)
    autotune_loop(spec,fc,pm) K-factor compensator design (BUCK)
    list_parameters()       parameter names/defaults for building a spec
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP  # noqa: E402

import design_api  # noqa: E402

mcp = FastMCP("psu-designer")

_SPEC_HINT = ("spec keys follow the GUI defaults (DEFAULT_PARAMS): topology "
              "{'BUCK','BOOST','BUCK-BOOST','FLYBACK','QR-FLYBACK','ACF-FORWARD'}, V_in, V_out, "
              "P_out, f_sw, L, C_out, Rc, N (flyback), Rds_on, Vf_diode, "
              "pm_target ...  SI values or {'v': x, 'u': 'k'} objects.")


@mcp.tool()
def run_design(spec_json: str) -> str:
    """Run a full switching-converter design: operating point, losses,
    magnetics, and a machine-readable check list (L_min/C_min/ripple/Bsat/
    temp-rise/PM ...).  Returns JSON {ok, topology, operating_point, losses,
    magnetics, checks[{id,name,value,limit,pass_}], failed_checks, warnings}."""
    try:
        spec = json.loads(spec_json)
    except Exception as e:
        return json.dumps(dict(ok=False, error=f'bad JSON: {e}'))
    return json.dumps(design_api.run_design(spec), default=str, ensure_ascii=False)


@mcp.tool()
def run_corners(spec_json: str, v_in_min: float = None,
                v_in_max: float = None) -> str:
    """Corner analysis: V_in-min/max (default ±10 %) × load {10..100 %}.
    Returns per-corner mode/eta/stress/ripple plus a worst-case summary."""
    try:
        spec = json.loads(spec_json)
    except Exception as e:
        return json.dumps(dict(ok=False, error=f'bad JSON: {e}'))
    return json.dumps(design_api.run_corners(spec, v_in_min, v_in_max),
                      default=str, ensure_ascii=False)


@mcp.tool()
def load_transient(spec_json: str, di: float, fc: float = None) -> str:
    """Load-step ΔV estimate: ESR step + capacitive droop until the loop
    responds.  di = load step in A; fc = loop crossover in Hz (default
    f_sw/10)."""
    try:
        spec = json.loads(spec_json)
    except Exception as e:
        return json.dumps(dict(ok=False, error=f'bad JSON: {e}'))
    return json.dumps(design_api.load_transient(spec, float(di),
                                                float(fc) if fc else None),
                      default=str, ensure_ascii=False)


@mcp.tool()
def autotune_loop(spec_json: str, fc: float, pm: float = 60.0) -> str:
    """Venable K-factor compensator design for a BUCK (voltage/peak-current
    mode) against target crossover fc [Hz] and phase margin pm [deg]; returns
    KP/zeros/poles plus the achieved (verified) fc and pm."""
    try:
        spec = json.loads(spec_json)
    except Exception as e:
        return json.dumps(dict(ok=False, error=f'bad JSON: {e}'))
    return json.dumps(design_api.autotune_loop(spec, float(fc), float(pm)),
                      default=str, ensure_ascii=False)


@mcp.tool()
def list_parameters() -> str:
    """All tunable parameters with their defaults (use to build a spec)."""
    return json.dumps(_SPEC_HINT and design_api.list_parameters(),
                      default=str, ensure_ascii=False)


@mcp.tool()
def validate_spec(spec_json: str) -> str:
    """Validate input only (not converter feasibility), with structured issues."""
    from design_engine.service import validate_spec as validate
    try:
        value = validate(json.loads(spec_json))
    except (ValueError, TypeError) as exc:
        value = dict(ok=False, issues=[dict(field='$', code='json', message=str(exc))])
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


@mcp.tool()
def parameter_schema() -> str:
    """Input JSON Schema derived from the same defaults and parameter catalogue."""
    from design_engine.catalog import specification_schema
    return json.dumps(specification_schema(), ensure_ascii=False, allow_nan=False)


@mcp.tool()
def design_snapshot(spec_json: str, analysis: str = 'selected') -> str:
    """Versioned strict-JSON snapshot. analysis: selected or endpoints.

    Returns compact summaries/checks, without detailed result/trace arrays. The
    CLI or Python service can produce full arrays. Cancellation propagates.
    """
    from design_engine.service import calculate, SpecValidationError
    try:
        return json.dumps(calculate(json.loads(spec_json), analysis=analysis).to_dict(include_waveforms=False, include_details=False),
                          ensure_ascii=False, allow_nan=False)
    except SpecValidationError as exc:
        return json.dumps(dict(ok=False, error='invalid_spec', issues=exc.issues), ensure_ascii=False)
    except (ValueError, TypeError) as exc:
        return json.dumps(dict(ok=False, error=str(exc)), ensure_ascii=False)


if __name__ == '__main__':
    mcp.run()
