import pandas as pd
import os
import subprocess
import numpy as np

from paths_and_settings import *
import prepare_targets_csv
import sample_targets_by_activity
import prepare_blast_on_targets
import get_best_found_decoys
from utils import log
import prepare_similarity
import reduce_actives_analogue_bias as raab

# uses prepare_targets_csvs
if INITIAL_FILTER:
    log('STARTING CREATING TARGETS CSV AND FIRST FILTERING STEPS')
    # First, let's just parse the csv file to extract compounds ChEMBL IDs:
    targets = pd.read_csv(RAW_TARGETS)
    # This will be our resulting structure mapping compound ChEMBL IDs into target uniprot IDs
    all_targets = list(targets['ChEMBL ID'])

    ki = pd.read_csv(RAW_KI_ACTIVITY, low_memory=False)
    ki_ids = set(ki['Target'])
    ki = prepare_targets_csv.duplicates_parser(ki)

    ic50 = pd.read_csv(RAW_IC50_ACTIVITY, low_memory=False)
    ic50_ids = set(ic50['Target'])
    ic50 = prepare_targets_csv.duplicates_parser(ic50)

    kd = pd.read_csv(RAW_KD_ACTVITY, low_memory=False)
    kd_ids = set(kd['Target'])
    kd = prepare_targets_csv.duplicates_parser(kd)

    log(f'All targets: {len(set(all_targets))}')
    filtered = list((ki_ids | ic50_ids | kd_ids) & set(all_targets))
    log(f'Targets with kd, ic50 or ki : {len(set(filtered))}')

    for index, row in targets.iterrows():
        k = row['ChEMBL ID']
        if k not in filtered:
            targets.drop(index, inplace=True)

    uniprot_3d = pd.read_csv(RAW_UNIPROT_3D_IDS, delimiter='\t', low_memory=False)
    uniprot_3d_entry = list(pd.read_csv(RAW_UNIPROT_3D_IDS, delimiter='\t', low_memory=False)['Entry'])

    targets['PDB_entry'] = ''

    for index, row in targets.iterrows():
        ifor_val = "No 3D"
        if row['UniProt Accession'] in uniprot_3d_entry:
            ifor_val = uniprot_3d[uniprot_3d['Entry'] == row['UniProt Accession']].iloc[0][
                'Cross-reference (PDB)'].replace(';', ' ')
            targets.at[index, 'PDB_entry'] = ifor_val
        else:
            targets.drop(index, inplace=True)

    print(f'Targets with any PDB structure : {len(targets)}')

    filtered = list(targets['ChEMBL ID'])

    ki = prepare_targets_csv.filter_csv_by_ids(filtered, ki, 'Target')
    kd = prepare_targets_csv.filter_csv_by_ids(filtered, kd, 'Target')
    ic50 = prepare_targets_csv.filter_csv_by_ids(filtered, ic50, 'Target')

    desired_units_ic50 = ['/uM', 'nM', 'ug.mL-1', np.nan]
    ic50 = prepare_targets_csv.filter_csv_by_units(desired_units_ic50, ic50)
    prepare_targets_csv.make_standard_csv(ic50, 'ic50')

    desired_units_ki = ['ug ml-1', 'nM', '/nM', np.nan]
    ki = prepare_targets_csv.filter_csv_by_units(desired_units_ki, ki)
    prepare_targets_csv.make_standard_csv(ki, 'ki')

    desired_units_kd = ['ug ml-1', 'nM', '/nM', '/uM', 'ug ml-1', np.nan]
    kd = prepare_targets_csv.filter_csv_by_units(desired_units_kd, kd)
    prepare_targets_csv.make_standard_csv(kd, 'kd')

    targets.index = list(targets['ChEMBL ID'])
    targets = prepare_targets_csv.add_compounds_with_std(targets, kd, standard_type='Kd')
    targets = prepare_targets_csv.check_activity_value_relation(targets, kd, 'Kd')

    targets = prepare_targets_csv.add_compounds_with_std(targets, ki, standard_type='Ki')
    targets = prepare_targets_csv.check_activity_value_relation(targets, ki, 'Ki')

    targets = prepare_targets_csv.add_compounds_with_std(targets, ic50, standard_type='IC50')
    targets = prepare_targets_csv.check_activity_value_relation(targets, ic50, 'IC50')

    targets = prepare_targets_csv.sum_act_inact(targets)
    try:
        targets.drop('Species Group Flag', axis=1)
    except:
        pass

    decois_ligands, decois_name_dict, decois_ligands_standards = prepare_targets_csv.decois_uniID_from_folder(
        DEKOIS_PATH, '.sdf')

    targets = prepare_targets_csv.decois_decoys_number_to_master(targets, decois_name_dict, decois_ligands,
                                                                 decois_ligands_standards)

    targets = prepare_targets_csv.check_if_dude_in_master(targets)

    targets.to_csv(MAIN_CSV_NAME)

    log(f'Targets at the end of first filtering: {len(targets)}')
    log('Finished first filtering step.')

if SAMPLING_FILTER:
    log(f'Starting sampling targets with attributes: activity threshold {LOWER_LIMIT_OF_LIGANDS}, Tanimoto similarity'
        f' thresholds: {LOWEST_TC_SIMILARITY_BETWEEN_LIGANDS_THRESHOLD}, PDB ligand weight lower threshold: {PDB_LIGANDS_WEIGHT_LOWER_THRESHOLD}')
    sample_targets_by_activity.sample_by_activity(activity_threshold=LOWER_LIMIT_OF_LIGANDS,
                                                  thresholds=LOWEST_TC_SIMILARITY_BETWEEN_LIGANDS_THRESHOLD,
                                                  ligand_threshold=PDB_LIGANDS_WEIGHT_LOWER_THRESHOLD)

# uses sample_targets_by_activity
if BLAST:
    log("Starting filtering targets by BLAST towards DUD-E and DEKOIS")
    # GET FASTAS THAT WILL BE USED DURING THE BLAST IN TERMINAL
    prepare_blast_on_targets.fetch_fastas_for_DEKOIS()
    prepare_blast_on_targets.fetch_fastas_for_DUDE()

    # run blasts
    source_csv = os.path.join(COMPOUND_SAMPLING_FOLDER,
                              f'targets_after_fingerprint_similarity{CHOSEN_LIGAND_LIMIT}_tc{CHOSEN_TC_THRESHOLD}.csv')
    source_fastas = os.path.join(BLAST_MAIN_FOLDER,
                                 f'targets_after_fingerprint_similarity{CHOSEN_LIGAND_LIMIT}_tc{CHOSEN_TC_THRESHOLD}-fastas.txt')
    prepare_blast_on_targets.fetch_fastas_for_chembl(source_csv, source_fastas)
    os.chdir(BLAST_MAIN_FOLDER)
    subprocess.call(f"makeblastdb -in {source_fastas} -dbtype prot", shell=True)
    subprocess.call(f"makeblastdb -in fastas_from_dude.txt -dbtype prot", shell=True)
    subprocess.call(f"makeblastdb -in fastas_from_dekois.txt -dbtype prot", shell=True)
    subprocess.call(
        f"blastp -db fastas_from_dude.txt -query {source_fastas} -out targets-dude_blast.txt -outfmt 10 -evalue {E_VALUE_THRESHOLD}",
        shell=True)
    subprocess.call(
        f"blastp -db fastas_from_dekois.txt -query {source_fastas} -out targets-dekois_blast.txt -outfmt 10 -evalue {E_VALUE_THRESHOLD}",
        shell=True)
    log('Finished BLASTING!')
    prepare_blast_on_targets.load_fasta_sequences(source_fastas,
                                                  os.path.join(BLAST_MAIN_FOLDER, 'fastas_from_dude.txt'),
                                                  os.path.join(BLAST_MAIN_FOLDER, 'targets-dude_blast.txt'))
    prepare_blast_on_targets.load_fasta_sequences(source_fastas,
                                                  os.path.join(BLAST_MAIN_FOLDER, 'fastas_from_dekois.txt'),
                                                  os.path.join(BLAST_MAIN_FOLDER, 'targets-dekois_blast.txt'))
    log('Finished reading BLAST outputs!')
    os.chdir(PROJECT_HOME)

    prepare_blast_on_targets.make_blast_csv(source_csv, [os.path.join(BLAST_MAIN_FOLDER, 'targets-dekois_blast.txt'),
                                                         os.path.join(BLAST_MAIN_FOLDER, 'targets-dude_blast.txt')])

    blast_results = pd.read_csv(os.path.join(BLAST_MAIN_FOLDER, 'chembl_blast_results.csv'), index_col=0,
                                dtype={1: str})
    blast_results['identity%_dekois'].fillna(0, inplace=True)
    blast_results['identity%_dude'].fillna(0, inplace=True)
    blast_results = blast_results[(blast_results['identity%_dekois'] <= MAX_BLAST_SIMILARITY) & (
            blast_results['identity%_dude'] <= MAX_BLAST_SIMILARITY)]
    blast_ids = list(blast_results.index.tolist())
    source_csv = pd.read_csv(source_csv, index_col=0)
    source_csv = source_csv[source_csv["ChEMBL ID"].isin(blast_ids)]
    source_csv.to_csv(
        os.path.join(PROJECT_HOME, f'master_table_final_{CHOSEN_LIGAND_LIMIT}_tc_{CHOSEN_TC_THRESHOLD}.csv'))

FINAL_TABLE_PATH = os.path.join(PROJECT_HOME, f'master_table_final_{CHOSEN_LIGAND_LIMIT}_tc_{CHOSEN_TC_THRESHOLD}.csv')

if CREATE_ACTIVES_SIMILARITY_MATRICES:
    prepare_similarity.prepare_actives_similarirty_matrices(FINAL_TABLE_PATH)

if FILTER_ACTIVES:
    source_csv = pd.read_csv(FINAL_TABLE_PATH, index_col=0)
    ids = source_csv['ChEMBL ID'].tolist()
    acts = raab.load_activities()
    if USE_JOBLIB:
        from joblib import Parallel, delayed
        log(f'Using JOBLIB with {JOBLIB_WORKERS} workers for actives filtering')
        best_actives_set = Parallel(n_jobs=JOBLIB_WORKERS)(delayed(raab.choose_best_actives)(target_id=target,
                                                                                             path_to_analog_matrix=join(
                                                                                                 SIMILARITY_MATRICES_FOLDER,
                                                                                                 f'{target}_AvA_similarity.csv'),
                                                                                             acts_dataframe=acts,
                                                                                             tc_threshold=ACTIVES_TC_SIMILARITY_THRESHOLD)
                                                           for target in ids)
        for ix in range(len(ids)):
            raab.filter_actives_smiles_file(target_id=ids[ix], best_actives=best_actives_set[ix])
            target_filtered_actives_path = os.path.join(CHEMBL_SMILES_FOLDER, f'{ids[ix]}_filtered_active.smi')

    else:
        for target in ids[-1]:
            target_best_actives = raab.choose_best_actives(target_id=target,
                                                           path_to_analog_matrix=join(SIMILARITY_MATRICES_FOLDER,
                                                                                      f'{target}_AvA_similarity.csv'),
                                                           acts_dataframe=acts,
                                                           tc_threshold=ACTIVES_TC_SIMILARITY_THRESHOLD)
            raab.filter_actives_smiles_file(target_id=target, best_actives=target_best_actives)
            target_filtered_actives_path = os.path.join(CHEMBL_SMILES_FOLDER, f'{target}_filtered_active.smi')

### AFTER DECOY SEARCHING

if FILTER_FOUND_DECOYS:
    _ = get_best_found_decoys.concat_found_decoys_results(FOUND_DECOYS_FOLDER)
    _ = get_best_found_decoys.add_tanimoto_score(FOUND_DECOYS_CSV)
    _ = get_best_found_decoys.sort_by_tanimoto(FOUND_DECOYS_CSV)
    get_best_found_decoys.filter_top_hits(FOUND_DECOYS_CSV, top=DECOYS_PER_LIGAND)
