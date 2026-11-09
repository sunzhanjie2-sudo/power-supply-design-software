"""Validated Whitney AV formulation; derived from the archived reference runner."""
import math
MU0=4e-7*math.pi

def sif(p,g,currents,name):
    blocks=[]
    for i,s in enumerate(g['physical_sections']):
        row=next(w for w in g['windings'] if w['id']==s['winding_id'])
        area=math.pi*row['bundle_width_m']*row['bundle_height_m']/4
        sign=(1 if s['direction']=='ccw' else -1)*(1 if s['dot_node']==s['start_node'] else -1)
        density=sign*currents[i]/(area*row['parallel_bundles'])
        blocks.append(f'''Body {i+3}
  Target Bodies(1) = {i+3}
  Name = {s['section_id']}
  Material = 1
  Equation = 1
  Body Force = {i+1}
End
Body Force {i+1}
  Current Density 1 = Variable Coordinate 1, Coordinate 2
    Real MATC "-({density:.16g})*tx(1)/sqrt(tx(0)^2+tx(1)^2)"
  Current Density 2 = Variable Coordinate 1, Coordinate 2
    Real MATC "({density:.16g})*tx(0)/sqrt(tx(0)^2+tx(1)^2)"
  Current Density 3 = Real 0.0
End
''')
    return f'''Header
  CHECK KEYWORDS Warn
  Mesh DB "." "mesh"
  Results Directory "{name}"
End
Simulation
  Coordinate System = Cartesian
  Simulation Type = Steady
  Steady State Max Iterations = 1
  Max Output Level = 4
End
Constants
  Permeability of Vacuum = {MU0:.16g}
End
Body 1
  Target Bodies(1) = 1
  Name = Air
  Material = 1
  Equation = 1
End
Body 2
  Target Bodies(1) = 2
  Name = Ferrite
  Material = 2
  Equation = 1
End
Material 1
  Relative Permeability = 1
  Relative Permittivity = 1
  Electric Conductivity = 0
End
Material 2
  Relative Permeability = {p['material']['relative_permeability']:.16g}
  Relative Permittivity = 1
  Electric Conductivity = 0
End
Equation 1
  Active Solvers(2) = 1 2
End
Solver 1
  Equation = MGDynamics
  Procedure = "MagnetoDynamics" "WhitneyAVSolver"
  Variable = A
  Fix Input Current Density = True
  Use Tree Gauge = True
  Linear System Solver = Direct
  Linear System Direct Method = MUMPS
  Linear System Symmetric = True
  Linear System Convergence Tolerance = 1e-9
  Nonlinear System Max Iterations = 1
End
Solver 2
  Equation = MagneticFields
  Procedure = "MagnetoDynamics" "MagnetoDynamicsCalcFields"
  Potential Variable = A
  Calculate Magnetic Field Strength = True
  Calculate Current Density = True
  Impose Body Force Current = True
  Calculate Elemental Fields = True
  Linear System Solver = Iterative
  Linear System Iterative Method = CG
  Linear System Preconditioning = ILU0
  Linear System Max Iterations = 3000
  Linear System Convergence Tolerance = 1e-10
  Linear System Abort Not Converged = True
End
Solver 3
  Exec Solver = After All
  Equation = ResultOutput
  Procedure = "ResultOutputSolve" "ResultOutputSolver"
  Output File Name = field
  Vtu Format = True
  Save Geometry Ids = True
  Save Bulk Only = True
End
Solver 4
  Exec Solver = After All
  Procedure = "SaveData" "SaveScalars"
  Filename = scalars.dat
End
Boundary Condition 1
  Target Boundaries(1) = 101
  A {{e}} = Real 0.0
  A = Real 0.0
  Jfix = Real 0.0
End
{''.join(blocks)}'''
