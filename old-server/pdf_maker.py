import json
import os
import sys
import requests
# https://pyfpdf.readthedocs.io
from fpdf import FPDF
from grid import parse_batch, generate_grid_and_cell_data

PDF_ROOT = f"{os.path.expanduser('~')}/pdfs"
# COLORS
BLACK = (0, 0, 0)
DARK = (64, 64, 64)
WHITE = (255, 255, 255)
LIGHT_GREY = (151, 151, 151)
GRAY = (240, 240, 240)

def partition(l, n):
    return [l[i * n:(i + 1) * n] for i in range((len(l) + n - 1) // n )]

class CustomPDF(FPDF):
    def __init__(self, batch, grid_data):
        # Landscape mode
        FPDF.__init__(self, orientation='L', unit='mm', format='A4')
        self.grid_data = grid_data['gridData']
        self.cell_data = grid_data['cellData']
        self.code_name = grid_data['codename']
        self.batch = batch
        self.num_wells, self.num_samples = parse_batch(batch)
        self.make_table()

    def header(self):
        # Set up a logo
        # self.image('snakehead.png', 10, 8, 33)
        self.set_font('Arial', '', 14)
        self.set_text_color(80, 80, 80)
        self.cell(10)
        self.cell(60, 5, f'{self.num_samples} Samples', 0)
        self.cell(30)
        self.cell(30, 5, f'{self.num_wells} Wells', 0)
        self.cell(30)
        self.cell(30, 5, f'Matrix: {self.code_name}', 0)
        # Add a page number
        self.cell(40)
        page = f'Page {self.page_no()}'
        self.cell(20, 5, page, 0, 0)
        # Line break
        self.ln(15)
    
    def make_table(self):
        g = [a['screenData'] for a in self.grid_data]
        # TODO Add all cells to be used in the first page
        c = self.cell_data
        samples = list(range(1, len(g)+1))
        max_l = max(len(c) for c in g)
        tables_per_page = 3 if max_l < 4 else 2
        rows_per_table = 15
        screen_partitions = partition(g, tables_per_page * rows_per_table)
        sample_partitions = partition(samples, tables_per_page * rows_per_table)
        ww = 17
        hh = 10
        self.set_text_color(*BLACK)
        for i in range(len(screen_partitions)):
            self.add_page()
            a = screen_partitions[i]
            b = sample_partitions[i] # Sample numbers
            tlist = partition(a, rows_per_table)
            slist = partition(b, rows_per_table)
            # Border color
            self.set_draw_color(*LIGHT_GREY)

            for j in range(len(tlist)):
                # Print sample numbers
                self.set_font('Arial', 'B', 11)
                self.set_text_color(*WHITE)
                self.set_fill_color(*DARK)
                self.cell(25, hh, f'Samples', 1, fill=True, align='C')
                for x in slist[j]:
                    self.cell(ww, hh, f'{x}', 1, fill=True, align='C')
                self.ln(hh)
                tt = tlist[j]
                self.set_fill_color(*GRAY)
                self.set_text_color(*BLACK)
                for k in range(max_l):
                    if k == 0:
                        self.cell(25, hh*max_l, f'Wells', 1, fill=True, align='C')
                    else:
                        self.cell(25, hh)
                    self.set_font('Arial', '', 12)
                    for i, x in enumerate(tt):
                        self.set_fill_color(*(GRAY if i%2 == 1 else WHITE))
                        if len(x) < max_l:
                            if type(x) == str:
                                x = []
                            x += ['' for _ in range(max_l - len(x))]
                        self.cell(ww, hh, x[k], 1, fill=True, align='C')
                    self.ln(hh)
                self.ln(20)

def create_pdf(batch):
    grid_resp = requests.get(f'https://c19.zyxw365.in/api/grid_data/{batch}').json()
    code_name = grid_resp['codename']
    pdf = CustomPDF(batch, grid_resp)    
    pdf.output(f'{PDF_ROOT}/{get_pdf_name(batch, code_name)}')

def get_pdf_name(batch, code_name):
    return f'{batch}_Matrix_{code_name}.pdf'

def generate_pdfs():
    batches = requests.get(f'https://c19.zyxw365.in/api/debug_info').json()['matrix_labels']
    for b in batches:
        print(f'Batch : {b}')
        create_pdf(b)

def generate_pdfs_locally(base_dir, batch_names):
    from compute_wrapper import get_matrix_sizes_and_labels, get_matrix_labels_and_matrices
    mlabels = get_matrix_sizes_and_labels()
    matrices = get_matrix_labels_and_matrices()
    for b in batch_names:
        m, n, i = mlabels[b]
        mat = matrices[m]
        g, c = generate_grid_and_cell_data(b, mat)
        grid_resp = {"gridData" : g["gridData"], "cellData" : c["cellData"], "codename" : "LOCAL"}
        pdf = CustomPDF(b, grid_resp)
        pdf.output(f'workdir/LOCAL_{b}.pdf')

if __name__ == "__main__":
    args = sys.argv
    if len(args) < 2:
        generate_pdfs()
    else:
        # workdir is in .gitignore, so generating local pdfs there
        pdf_dir = "workdir"
        if not os.path.exists(pdf_dir):
            print(f"Creating {pdf_dir} as it does not exist")
            os.makedirs(pdf_dir)
        generate_pdfs_locally(pdf_dir, args[1:])
