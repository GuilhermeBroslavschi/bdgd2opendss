# -*- encoding: utf-8 -*-
import inspect
import json
import os.path
import pathlib
import time
from dataclasses import dataclass
from typing import List

import geopandas as gpd

import bdgd2opendss.model.BusCoords as Coords
from bdgd2opendss import Case, Circuit, LineCode, Line, LoadShape, Transformer, RegControl, Load, PVsystem
from bdgd2opendss.core.Utils import inner_entities_tables, create_output_feeder_coords, create_dfs_coords

# parameters class. To be defined by the user.
@dataclass
class Parameters:

    def __init__(self, bdgdPath: str, alim: str, allFeeders=False, limitRamal30m=True,
                 ger4fios=True, gerCapacitors=False, loadModel="ANEEL", genMT="asBDGD", genBT="generator", gerCoord=True):
        self.folder_bdgd = bdgdPath         # BDGD path
        self.alimentador = alim             # feeder name
        self.allFeeders = allFeeders        # generates all feeders
        self.limitRamal30m = limitRamal30m  # limits ramal to 30m
        self.ger4fios = ger4fios            # generates with Neutral
        self.gerCapacitors = gerCapacitors  # generates capacitors banks
        self.loadModel = loadModel          # loadModel ANEEL (e.g 2 loads for each load), model8
        self.genTypeMT = genMT              # chooses between: "generator" / "PVSystem" / "asBDGD"
        self.genTypeBT = genBT              # chooses between: "generator" / "PVSystem" /
        self.gerCoord = gerCoord            # boolean to control the geographic generation

class Table:
    def __init__(self, name, columns, data_types, ignore_geometry_):
        self.name = name
        self.columns = columns
        self.data_types = data_types
        self.ignore_geometry = ignore_geometry_

    def __str__(self):
        return f"Table(name={self.name}, columns={self.columns}, data_types={self.data_types}, " \
               f"ignore_geometry={self.ignore_geometry})"

class JsonData:
    def __init__(self, file_name):
        """
        Inicializa a classe JsonData com o nome do arquivo de entrada.

        :param file_name: Nome do arquivo JSON de entrada.
        """
        self.data = self._read_json_file(file_name)
        self.tables = self._create_tables()

    @staticmethod
    def _read_json_file(file_name):
        """
        Lê o arquivo JSON fornecido e retorna o conteúdo como um objeto Python.

        :param file_name: Nome do arquivo JSON de entrada.
        :return: Objeto Python contendo o conteúdo do arquivo JSON.
        """
        with open(file_name, 'r', encoding='utf-8') as file:
            data = json.load(file)
        return data

    def _create_tables(self):
        """
        Cria um dicionário de tabelas a partir dos dados carregados do arquivo JSON.

        :return: Dicionário contendo informações das tabelas a serem processadas.
        """
        return {
            table_name: Table(
                table_name,
                table_data["columns"],
                table_data["type"],
                table_data["ignore_geometry"],
            )
            for table_name, table_data in self.data["configuration"][
                "tables"
            ].items()
        }

    def get_tables(self):
        """
        Retorna o dicionário de tabelas.

        :return: Dicionário contendo informações das tabelas a serem processadas.
        """
        return self.tables

    @staticmethod
    def convert_data_types(df, column_types):
        """
        Converte os tipos de dados das colunas do DataFrame fornecido.

        :param df: DataFrame a ser processado.
        :param column_types: Dicionário contendo mapeamento de colunas para tipos de dados.
        :return: DataFrame com tipos de dados convertidos.
        """
        return df.astype(column_types)

    def create_geodataframes(self, file_name, runs=1):
        """
        Cria GeoDataFrames a partir de um arquivo de entrada e coleta estatísticas.

        :param file_name: Nome do arquivo de entrada.
        :param runs: Número de vezes que cada tabela será carregada e convertida (padrão: 1).
        :return: Dicionário contendo GeoDataFrames e estatísticas.
        """
        geodataframes = {}

        for table_name, table in self.tables.items():

            load_times = []
            conversion_times = []
            gdf_converted = None

            for _ in range(runs):
                start_time = time.time()
                gdf_ = gpd.read_file(file_name, layer=table.name,
                                     include_fields=table.columns, columns=table.columns,
                                     ignore_geometry=table.ignore_geometry, engine='pyogrio',
                                     use_arrow=True)  # ! ignore_geometry não funciona, pq este parâmetro espera um bool e está recebendo str
                start_conversion_time = time.time()
                gdf_converted = self.convert_data_types(gdf_, table.data_types)
                end_time = time.time()

                load_times.append(start_conversion_time - start_time)
                conversion_times.append(end_time - start_conversion_time)

            load_time_avg = sum(load_times) / len(load_times)
            conversion_time_avg = sum(conversion_times) / len(conversion_times)
            mem_usage = gdf_converted.memory_usage(index=True, deep=True).sum() / 1024 ** 2

            geodataframes[table_name] = {
                'gdf': gdf_converted,
                'memory_usage': mem_usage,
                'load_time_avg': load_time_avg,
                'conversion_time_avg': conversion_time_avg,
                'ignore_geometry': table.ignore_geometry
            }
        return geodataframes

    def create_geodataframes_lista_ctmt(self, file_name):
        """
        :return: Dicionário contendo GeoDataFrames.
        """
        geodataframes = {}

        for table_name, table in self.tables.items():
            gdf_ = gpd.read_file(file_name, layer="CTMT", columns=table.columns,
                                 engine='pyogrio', use_arrow=True)

            geodataframes[table_name] = {
                'gdf': gdf_
            }
        return geodataframes

def get_caller_directory(caller_frame: inspect) -> pathlib.Path:
    """
    Returns the file directory that calls this function.

    :param caller_frame: The frame that call the function.
    :return: A Pathlib.path object representing the file directory that called this function.
    """
    caller_file = inspect.getfile(caller_frame)
    return pathlib.Path(caller_file).resolve().parent

def get_feeder_list(folder: str) -> List[str]:  # TODO is there a way to not load everything?
    folder_bdgd = folder
    json_file_name = os.path.join(os.getcwd(), "bdgd2dss.json")

    json_data = JsonData(json_file_name)
    geodataframes = json_data.create_geodataframes_lista_ctmt(folder_bdgd)

    return geodataframes["CTMT"]['gdf']['COD_ID'].tolist()

def export_feeder_list(feeder_list, feeder):

    if not os.path.exists("dss_models_output"):
        os.mkdir("dss_models_output")

    if not os.path.exists(f'dss_models_output/{feeder}'):
        os.mkdir(f'dss_models_output/{feeder}')

    output_directory = os.path.join(os.getcwd(), f'dss_models_output\{feeder}')

    path = os.path.join(output_directory, f'Alimentadores.txt')
    with open(path,'w') as output:
        for k in feeder_list:
            output.write(str(k)+"\n")
    return f'Lista de alimentadores criada em {path}'

def run( par: Parameters ) :

    json_file_name = os.path.join(os.getcwd(), "bdgd2dss.json")

    json_data = JsonData(json_file_name)

    geodataframes = json_data.create_geodataframes(par.folder_bdgd)

    # generates all feeders
    if par.allFeeders :

        # TO DO refatorar. Vide comentario TO DO abaixo.
        for alimentador in geodataframes["CTMT"]['gdf']['COD_ID'].tolist():

            par.alimentador = alimentador

            populaCase(json_data.data, geodataframes, par)

    else :

        # verifies if the feeder exists
        if par.alimentador not in geodataframes["CTMT"]['gdf']['COD_ID'].tolist() :
            print(f"\nFeeder: {par.alimentador} not found in CTMT.")
            return

        populaCase(json_data.data, geodataframes, par)

# this method populates Case object with data from BDGD
# TODO so it makes sense to be a method of Case class (or any other class...)
def populaCase(jsonData, geodataframes, par):

    alimentador = par.alimentador

    # generates the geographic coordinates
    if par.gerCoord:
        gdf_SSDMT, gdf_SSDBT = create_dfs_coords(par.folder_bdgd, alimentador)
        df_coords = Coords.get_buscoords(gdf_SSDMT, gdf_SSDBT)
        create_output_feeder_coords(df_coords, alimentador)

    case = Case()
    case.dfs = geodataframes
    case.id = alimentador
    print(f"\nFeeder: {alimentador}")

    list_files_name = []

    # CTMT
    try:
        case.circuitos, fileName = Circuit.create_circuit_from_json(jsonData, case.dfs['CTMT']['gdf'].query(
            "COD_ID==@alimentador"))
        list_files_name.append(fileName)

    except UnboundLocalError:
        print("Error in CTMT.\n")

    # SEGCON
    try:
        case.line_codes, fileName = LineCode.create_linecode_from_json(jsonData, case.dfs['SEGCON']['gdf'],
                                                                       alimentador)
        list_files_name.append(fileName)

    except UnboundLocalError:
        print("Error in SEGCON.\n")

    #
    for entity in ['SSDMT', 'UNSEMT', 'SSDBT', 'UNSEBT', 'RAMLIG']:

        # SSDMT
        if not case.dfs[entity]['gdf'].query("CTMT == @alimentador").empty:

            try:
                case.lines_SSDMT, fileName, aux_em = Line.create_line_from_json(jsonData,
                                                                                case.dfs[entity]['gdf'].query("CTMT==@alimentador"),
                                                                                entity,ramal_30m=par.limitRamal30m)

                list_files_name.append(fileName)
                if aux_em != "":
                    list_files_name.append(aux_em)

            except UnboundLocalError:
                print(f"Error in {entity}.\n")

    # UNREMT
    # do the merge before checking if result set is empty
    merged_dfs = inner_entities_tables(case.dfs['EQRE']['gdf'], case.dfs['UNREMT']['gdf'].query("CTMT==@alimentador"),
                                       left_column='UN_RE', right_column='COD_ID')

    # OLD CODE if not case.dfs['UNREMT']['gdf'].query("CTMT == @alimentador").empty:
    if not merged_dfs.query("CTMT == @alimentador").empty:

        try:
            case.regcontrols, fileName = RegControl.create_regcontrol_from_json(jsonData,merged_dfs)
            list_files_name.append(fileName)

        except UnboundLocalError:
             print("Error in UNREMT.\n")

    else:
        if case.dfs['UNREMT']['gdf'].query("CTMT == @alimentador").empty:
            print("No RegControls found for this feeder.\n")
        else :
            print("Error. Please, check the association EQRE/UNREMT for this feeder.\n")

    # UNTRMT
    merged_dfs = inner_entities_tables(case.dfs['EQTRMT']['gdf'], case.dfs['UNTRMT']['gdf'].query("CTMT==@alimentador"),
                                       left_column='UNI_TR_MT', right_column='COD_ID')
    if not merged_dfs.query("CTMT == @alimentador").empty:
        try:

            case.transformers, fileName = Transformer.create_transformer_from_json(jsonData,merged_dfs)
            list_files_name.append(fileName)

        except UnboundLocalError:
            print("Error in UNTRMT.\n")

    else:
        print("Error. Please, check the association EQTRMT/UNTRMT for this feeder.\n")

    # CRVCRG
    try:
        case.load_shapes, fileName = LoadShape.create_loadshape_from_json(jsonData, case.dfs['CRVCRG']['gdf'],
                                                                          alimentador)
        list_files_name.append(fileName)

    except UnboundLocalError:
        print("Error in CRVCRG\n")

    # UCBT_tab
    if not case.dfs['UCBT_tab']['gdf'].query("CTMT == @alimentador").empty:

        try:
            case.loads, fileName = Load.create_load_from_json(jsonData,
                                                              case.dfs['UCBT_tab']['gdf'].query("CTMT==@alimentador"),
                                                              case.dfs['CRVCRG']['gdf'], 'UCBT_tab')
            list_files_name.append(fileName)

        except UnboundLocalError:
            print("Error in UCBT_tab\n")

    else:
        print(f'No UCBT found for this feeder.\n')

    # PIP
    if not case.dfs['PIP']['gdf'].query("CTMT == @alimentador").empty:

        try:
            case.loads, fileName = Load.create_load_from_json(jsonData,
                                                              case.dfs['PIP']['gdf'].query("CTMT==@alimentador"),
                                                              case.dfs['CRVCRG']['gdf'], 'PIP')
            list_files_name.append(fileName)

        except UnboundLocalError:
            print("Error in PIP\n")

    else:
        print(f'No PIP found for this feeder.\n')

    # UCMT
    if not case.dfs['UCMT_tab']['gdf'].query("CTMT == @alimentador").empty:

        try:
            case.loads, fileName = Load.create_load_from_json(jsonData,
                                                              case.dfs['UCMT_tab']['gdf'].query("CTMT==@alimentador"),
                                                              case.dfs['CRVCRG']['gdf'], 'UCMT_tab')
            list_files_name.append(fileName)

        except UnboundLocalError:
            print("Error in UCMT\n")
    else:
        print(f'No UCMT found for this feeder.\n')

    # UGBT_tab
    if not case.dfs['UGBT_tab']['gdf'].query("CTMT == @alimentador").empty:

        try:
            case.pvsystems, fileName = PVsystem.create_pvsystem_from_json(jsonData, case.dfs['UGBT_tab']['gdf'].query(
                "CTMT==@alimentador"), 'UGBT_tab')
            list_files_name.append(fileName)

        except UnboundLocalError:
            print("Error in UGBT_tab\n")

    else:
        print("No UGBT found for this feeder. \n")

    # UGMT_tab
    if not case.dfs['UGMT_tab']['gdf'].query("CTMT == @alimentador").empty:

        try:
            case.pvsystems, fileName = PVsystem.create_pvsystem_from_json(jsonData, case.dfs['UGMT_tab']['gdf'].query(
                "CTMT==@alimentador"), 'UGMT_tab')
            list_files_name.append(fileName)

        except UnboundLocalError:
            print("Error in UGBT_tab\n")
    else:
        print("No UGMT found for this feeder. \n")

    # creates dss files
    case.output_master(list_files_name)
    case.create_outputs_masters(list_files_name)
