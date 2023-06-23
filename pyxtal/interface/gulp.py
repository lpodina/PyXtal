import os
import numpy as np
import re
from pyxtal import pyxtal
from pyxtal.lattice import Lattice
from ase import Atoms
from ase.units import eV, Ang

class GULP():
    """
    This is a calculator to perform structure optimization in GULP
    At the moment, only inorganic crystal is considered

    Args:

    struc: structure object generated by Pyxtal
    ff: path of forcefield lib
    opt: `conv`, `conp`, `single`
    pstress (float): external pressure
    steps (int): relaxation steps
    symm (bool): whether or not impose the symmetry
    """

    def __init__(self, struc, label="_", path='tmp', ff='reax', \
                 pstress=None, opt='conp', steps=1000, exe='gulp',\
                 input='gulp.in', output='gulp.log', dump=None,
                 symmetry=False, labels=None):

        if isinstance(struc, pyxtal):
            self.pyxtal = struc
            self.species = struc.species
            struc = struc.to_ase(resort=False)
        else:
            self.pyxtal = None

        if isinstance(struc, Atoms):
            self.lattice = Lattice.from_matrix(struc.cell)
            self.frac_coords = struc.get_scaled_positions()
            self.sites = struc.get_chemical_symbols()
            self.species = None
        else:
            raise NotImplementedError("only support ASE atoms object")
        
        self.symmetry = symmetry#; print(self.pyxtal.lattice.ltype)
        self.structure = struc
        self.pstress= pstress
        self.label = label
        self.labels = labels
        self.ff = ff
        self.opt = opt
        self.exe = exe
        self.steps = steps
        self.folder = path  
        if not os.path.exists(self.folder):
            os.makedirs(self.folder)
        self.input = self.folder + '/' + self.label + input
        self.output = self.folder + '/' + self.label + output
        self.dump = dump
        self.iter = 0
        self.energy = None
        self.energy_per_atom = None
        self.stress = None
        self.forces = None
        self.positions = None
        self.optimized = False
        self.cputime = 0
        self.error = False

    def set_catlow(self):
        """
        set the atomic label for catlow potentials
        O_O2- general O2- species
        O_OH oxygen in hydroxyl group
        H_OH hydrogen in hydroxyl group
        """
        pass

    def run(self, clean=True):
        self.write()
        self.execute()
        self.read()
        if clean:
            self.clean()

    def execute(self):
        cmd = self.exe + '<' + self.input + '>' + self.output
        os.system(cmd)

    def clean(self):
        os.remove(self.input)
        os.remove(self.output)
        if self.dump is not None:
            os.remove(self.dump)

    def to_ase(self):
        return Atoms(self.sites, scaled_positions=self.frac_coords, cell=self.lattice.matrix)

    def to_pymatgen(self):
        from pymatgen.core.structure import Structure
        return Structure(self.lattice.matrix, self.sites, self.frac_coords)

    def to_pyxtal(self):
        ase_atoms = self.to_ase()
        for tol in [1e-2, 1e-3, 1e-4, 1e-5]:
            try:
                struc = pyxtal()
                struc.from_seed(ase_atoms, tol=tol)
                break
            except:
                pass
                #print('Something is wrong', tol)
                #struc.from_seed('bug.vasp', tol*10)
        return struc

    def write(self):
        a, b, c, alpha, beta, gamma = self.lattice.get_para(degree=True)
        
        with open(self.input, 'w') as f:
            if self.opt == 'conv':
                f.write('opti stress {:s} conjugate '.format(self.opt))
            elif self.opt == "single":
                f.write('grad conp stress ')
            else:
                f.write('opti stress {:s} conjugate '.format(self.opt))

            if not self.symmetry:
                f.write('nosymmetry\n')

            f.write('\ncell\n')
            f.write('{:12.6f}{:12.6f}{:12.6f}{:12.6f}{:12.6f}{:12.6f}\n'.format(\
                    a, b, c, alpha, beta, gamma))
            f.write('\nfractional\n')
            
            symbols = []
            if self.symmetry and self.pyxtal is not None:
                # Use pyxtal here
                for site in self.pyxtal.atom_sites:
                    symbol, coord = site.specie, site.position
                    f.write('{:4s} {:12.6f} {:12.6f} {:12.6f} core \n'.format(symbol, *coord))
                    if self.ff == 'catlow' and symbol == 'O':
                        f.write('{:4s} {:12.6f} {:12.6f} {:12.6f} shell \n'.format(symbol, *coord))


                # Tested for all space groups
                f.write('\nspace\n{:d}\n'.format(self.pyxtal.group.number))
                f.write('\norigin\n0 0 0\n')
            else:
                # All coordinates
                for coord, site in zip(self.frac_coords, self.sites):
                    f.write('{:4s} {:12.6f} {:12.6f} {:12.6f} core \n'.format(site, *coord))
            if self.species is not None:
                species = self.structure.species
            else:
                species = list(set(self.sites))

            f.write('\nSpecies\n')
            if self.labels is not None:
                for specie in species:
                    if specie in self.labels.keys():
                        sp = self.labels[specie]
                        f.write('{:4s} core {:s}\n'.format(specie, sp))
                    else:
                        f.write('{:4s} core {:4s}\n'.format(specie, specie))
            else:
                for specie in species:
                    if self.ff == 'catlow' and specie == 'O':
                        f.write('O    core O_O2- core\n')
                        f.write('O    shell O_O2- shell\n')
                    else:
                        f.write('{:4s} core {:4s}\n'.format(specie, specie))

            f.write('\nlibrary {:s}\n'.format(self.ff))
            f.write('ewald 10.0\n')
            #f.write('switch rfo gnorm 1.0\n')
            #f.write('switch rfo cycle 0.03\n')
            if self.opt != "single":
                f.write('maxcycle {:d}\n'.format(self.steps))
            if self.pstress is not None:
                f.write("pressure {:6.3f}\n".format(self.pstress))
            if self.dump is not None:
                f.write('output cif {:s}\n'.format(self.dump))


    def read(self):
        # for symmetry case
        lattice_para = None
        lattice_vector = None
        if self.pyxtal is not None:
            ltype = self.pyxtal.lattice.ltype
        else:
            ltype = 'triclinic'

        with open(self.output, 'r') as f:
            lines = f.readlines()
        try: 
            for i, line in enumerate(lines):
                if self.symmetry and self.pyxtal.group.symbol[0] != 'P':
                    m = re.match(r'\s*Non-primitive unit cell\s*=\s*(\S+)\s*eV', line)
                elif self.pstress is None or self.pstress == 0:
                    m = re.match(r'\s*Total lattice energy\s*=\s*(\S+)\s*eV', line)
                else:
                    m = re.match(r'\s*Total lattice enthalpy\s*=\s*(\S+)\s*eV', line)
                #print(line.find('Final asymmetric unit coord'), line)
                if m:
                    self.energy = float(m.group(1))
                    self.energy_per_atom = self.energy/len(self.frac_coords)

                elif line.find('Job Finished')!= -1:
                    self.optimized = True

                elif line.find('Total CPU time') != -1:
                    self.cputime = float(line.split()[-1])

                elif line.find('Final stress tensor components')!= -1:
                    stress = np.zeros([6])
                    for j in range(3):
                        var=lines[i+j+3].split()[1]
                        stress[j]=float(var)
                        var=lines[i+j+3].split()[3]
                        stress[j+3]=float(var)
                    self.stress = stress

                # Forces, QZ copied from https://gitlab.com/ase/ase/-/blob/master/ase/calculators/gulp.py
                elif line.find('Final internal derivatives') != -1:
                    s = i + 5
                    forces = []
                    while(True):
                        s = s + 1
                        if lines[s].find("------------") != -1:
                            break
                        g = lines[s].split()[3:6]

                        for t in range(3-len(g)):
                            g.append(' ')
                        for j in range(2):
                            min_index=[i+1 for i,e in enumerate(g[j][1:]) if e == '-']
                            if j==0 and len(min_index) != 0:
                                if len(min_index)==1:
                                    g[2]=g[1]
                                    g[1]=g[0][min_index[0]:]
                                    g[0]=g[0][:min_index[0]]
                                else:
                                    g[2]=g[0][min_index[1]:]
                                    g[1]=g[0][min_index[0]:min_index[1]]
                                    g[0]=g[0][:min_index[0]]
                                    break
                            if j==1 and len(min_index) != 0:
                                g[2]=g[1][min_index[0]:]
                                g[1]=g[1][:min_index[0]]

                        G = [-float(x) * eV / Ang for x in g]
                        forces.append(G)
                    forces = np.array(forces)
                    self.forces = forces

                elif line.find(' Cycle: ') != -1:
                    self.iter = int(line.split()[1])
    
                # asymmetric unit
                elif line.find('Final asymmetric unit coordinates') != -1:
                    s = i + 6
                    positions = []
                    for _i in range(len(self.pyxtal.atom_sites)):
                        xyz = lines[s+_i].split()[3:6]
                        XYZ = [float(x) for x in xyz]
                        #print(XYZ)
                        self.pyxtal.atom_sites[_i].update(XYZ)

                elif line.find('Final fractional coordinates of atoms') != -1:
                    s = i + 5
                    positions = []
                    species = []
                    while True:
                        s = s + 1
                        if lines[s].find("------------") != -1:
                            break
                        xyz = lines[s].split()[3:6]
                        XYZ = [float(x) for x in xyz]
                        positions.append(XYZ)
                        species.append(lines[s].split()[1])
                    #if len(species) != len(self.sites):
                    #    print("Warning", len(species), len(self.sites))
                    self.frac_coords = np.array(positions)
                elif line.find('Final Cartesian lattice vectors') != -1:
                    lattice_vectors = np.zeros((3,3))
                    s = i + 2
                    for j in range(s, s+3):
                        temp=lines[j].split()
                        for k in range(3):
                            lattice_vectors[j-s][k]=float(temp[k])
                    lattice_vector = Lattice.from_matrix(lattice_vectors, ltype=ltype)

                elif line.find('Non-primitive lattice parameters') != -1:
                    s = i + 2
                    temp = lines[s].split()
                    a, b, c = float(temp[2]), float(temp[5]), float(temp[8])
                    temp = lines[s+1].split()
                    alpha, beta, gamma = float(temp[1]), float(temp[3]), float(temp[5])
                    lattice_para = Lattice.from_para(a, b, c, alpha, beta, gamma, ltype)
        except:
            self.error = True
            self.energy = None
        if lattice_para is not None:
            self.lattice = lattice_para
        elif lattice_vector is not None:
            self.lattice = lattice_vector
        else:
            self.error = True
            self.energy = None

        if self.pyxtal is not None:
            self.pyxtal.lattice = self.lattice

        if self.energy is None or np.isnan(self.energy):
            self.error = True
            self.energy = None
            print("GULP calculation is wrong, reading------")

def single_optimize(struc, ff, steps=1000, pstress=None, opt="conp", 
                    exe="gulp", path="tmp", label="_", clean=True,
                    symmetry=False, labels=None):

    calc = GULP(struc, steps=steps, label=label, path=path, 
                pstress=pstress, ff=ff, opt=opt, 
                symmetry=symmetry, labels=labels)

    calc.run(clean=clean)

    if calc.error:
        print("GULP error in single optimize")
        return None, None, 0, True
    else:
        if calc.pyxtal is None:
            struc = calc.to_pyxtal()
        else:
            struc = calc.pyxtal
        #if sum(struc.numIons) == 42: print("SSSSS"); import sys; sys.exit()   
        return struc, calc.energy_per_atom, calc.cputime, calc.error

def optimize(struc, ff, optimizations=["conp", "conp"], exe="gulp", 
            pstress=None, path="tmp", label="_", clean=True, adjust=False):
    """
    Multiple calls

    """
    time_total = 0
    for opt in optimizations:
        struc, energy, time, error = single_optimize(struc, ff, 
        pstress=pstress, opt=opt, exe=exe, path=path, label=label, clean=clean)

        time_total += time
        if error:
            return None, None, 0, True
        elif adjust and abs(energy)<1e-8:
            matrix = struc.lattice.matrix
            struc.lattice.set_matrix(matrix*0.8)
            
    return struc, energy, time_total, False


if __name__ == "__main__":

    while True:
        struc = pyxtal()
        struc.from_random(3, 19, ["C"], [4])
        if struc.valid:
            break
    print(struc)
    pmg1 = struc.to_pymatgen()
    calc = GULP(struc, opt="single", ff="tersoff.lib")
    calc.run(clean=False)#; import sys; sys.exit()
    print(calc.energy)
    print(calc.stress)
    print(calc.forces)
    pmg2 = calc.to_pymatgen()
    #xtal = calc.pyxtal #calc.to_pyxtal()
    #print(calc.iter)
    #print(xtal)

    import pymatgen.analysis.structure_matcher as sm
    print(sm.StructureMatcher().fit(pmg1, pmg2))

    struc, eng, time, _ = optimize(struc, ff="tersoff.lib")
    print(struc)
    print(eng)
    print(time)
