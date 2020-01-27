import warnings
warnings.simplefilter(action="ignore", category=FutureWarning)
import osmnx as ox, networkx as nx, matplotlib.cm as cm, pandas as pd, numpy as np, geopandas as gpd
import math
from math import sqrt
import ast
import functools

from shapely.geometry import Point, LineString, Polygon
pd.set_option("precision", 10)

from .utilities import *
from .angles import *

"""
This set of functions handles interoperations between GeoDataFrames and graphs. It allows data conversion and the extraction of nodes and edges GeoDataFrames from roads shapefile or OpenStreetMap.

"""
    
## Graph preparation functions ###############
    
def get_network_fromOSM(download_type, place, network_type = "all", epsg = None, distance = 7000): 

    """
    The function downloads and creates a simplified OSMNx graph for a selected area. 
    Afterwards, GeoDataFrames for nodes and edges are created, assigning new nodeID and edgeID identifiers.
        
    Parameters
    ----------
    download_type: string, {"OSMpolygon", "distance_from_address", "OSMplace"}
        it indicates the method that should be used for downloading the data. of dowload
    place: string
        name of cities or areas in OSM: when using "OSMpolygon" please provide the name of a "relation" in OSM as an argument of "place"; when using "distance_from_address"
        provide an existing OSM address; when using "OSMplace" provide an OSM place name
    network_type: string,  {"walk", "bike", "drive", "drive_service", "all", "all_private", "none"}
        it indicates type of street or other network to extract - from OSMNx paramaters
    epsg: int
        epsg of the area considered; if None OSMNx is used for the projection
    distance: float
        it is used only if download_type == "distance from address"
        
    Returns
    -------
    tuple of GeoDataFrames
    """
    
    # using OSMNx to download data from OpenStreetMap     
    if download_type == "OSMpolygon":
        query = ox.osm_polygon_download(place, limit=1, polygon_geojson=1)
        OSMplace = query[0]["display_name"]
        G = ox.graph_from_place(OSMplace, network_type = network_type, simplify = True)
        
    elif download_type == "distance_from_address":
        G = ox.graph_from_address(place, network_type = network_type, distance = distance, simplify = True)
    
    # (download_type == "OSMplace")
    else: G = ox.graph_from_place(place, network_type = network_type, simplify = True)
    
    # fix list of osmid assigned to same edges
    for i, item in enumerate(G.edges()):
        if isinstance(G[item[0]][item[1]][0]["osmid"], (list,)): 
            G[item[0]][item[1]][0]["osmid"] = G[item[0]][item[1]][0]["osmid"][0]
            
    nodes = ox.graph_to_gdfs(G, nodes=True, edges=False, node_geometry=True, fill_edge_geometry=False)
    nodes_gdf = nodes.drop(["highway", "ref"], axis=1, errors = "ignore")
    edges = ox.graph_to_gdfs(G, nodes=False, edges=True, node_geometry=False, fill_edge_geometry=True)
    edges_gdf = edges[["geometry", "length", "osmid", "u","v", "highway","key", "oneway", "maxspeed","name"]]
    
    # getting rid of OSMid and preparing geodataframes
    edges_gdf = edges_gdf.rename(columns = {"u":"old_u", "v":"old_v"})
    nodes_gdf = nodes_gdf.reset_index(drop=True)
    nodes_gdf["old_nodeID"] = nodes_gdf.osmid.astype("int64")
    nodes_gdf["nodeID"] = nodes_gdf.index.values.astype(int)
    
    edges_gdf = pd.merge(edges_gdf, nodes_gdf[["old_nodeID", "nodeID"]], how="left", left_on="old_u", right_on="old_nodeID")
    edges_gdf = edges_gdf.rename(columns = {"nodeID":"u"})
    edges_gdf = pd.merge(edges_gdf, nodes_gdf[["old_nodeID", "nodeID"]], how="left", left_on="old_v", right_on="old_nodeID")
    edges_gdf = edges_gdf.rename(columns = {"nodeID":"v"})
    
    # reset index                          
    edges_gdf = edges_gdf.reset_index(drop=True)
    edges_gdf["edgeID"] = edges_gdf.index.values.astype(int)
                                            
    # columns to keep (u and v represent "from" and "to" node)
    nodes_gdf = nodes_gdf[["nodeID","x","y","geometry"]]
    edges_gdf = edges_gdf[["edgeID","u","v","key","geometry", "length", "highway","oneway", "name"]]
    edges_gdf["oneway"] *= 1
    
    # resolving lists 
    edges_gdf["highway"] = [x[0] if type(x) == list else x for x in edges_gdf["highway"]]
    edges_gdf["name"] = [x[0] if type(x) == list else x for x in edges_gdf["name"]]
    
    # finalising geodataframes
    if epsg == None: nodes_gdf, edges_gdf = ox.projection.project_gdf(nodes_gdf), ox.projection.project_gdf(edges_gdf)
    else: nodes_gdf, edges_gdf = nodes_gdf.to_crs(epsg = epsg), edges_gdf.to_crs(epsg = epsg)
    
    nodes_gdf["x"], nodes_gdf["y"] = list(zip(*[(r.coords[0][0], r.coords[0][1]) for r in nodes_gdf.geometry]))
    nodes_gdf['height'] = 2 # this will be used for 3d visibility analysis
    return nodes_gdf, edges_gdf

def get_network_fromSHP(path, epsg, case_study_area = None, distance_from_boundary = 800,
                        distance_from_center = 2000, dict_columns = {}):
    
    """
    The function loads a vector lines shapefile from a specified directory, along with the epsg coordinate code.
    It creates two GeoDataFrame, one for street junctions (nodes) and one for street segments (edges).
    The GeoDataFrames are built assuming a planar undirected graph. 
    The "case_study_area" polygon is optional and when provided is used to select geometries within the area + a buffer of x meters, fixed by the researcher (distance_from_boundary)
     
    Parameters
    ----------
    path: string
        the local path where the .shp file is stored
    epsg: int
        epsg of the area considered 
    case_study_area: Polygon
        the polygon representing the extension of the case-study area, if not provided the 2 following parameters are used to extract the street network
    distance_from_boundary: float
        the distance from the edge of the case-study area used to compute centrality measures in a more sound way, preventing the edge effect
    distance_from_center: float
        it is employed, when the case_study_area polygon is not provided, to determine the extension of the area of interest
    dict_columns: dict
        it should be structured as: {roadType_field: "highway", direction_field: "oneway", speed_field: None, name_field: "name"} 
        Replace the items with the field names in the input data (if the relative attributes are relevant and existing)
    
    Returns
    -------
    tuple of GeoDataFrames
    """
    
    # try reading street network from directory
    streets_gdf = gpd.read_file(path).to_crs(epsg=epsg)
        
    # using a buffer to clip the area of study
    if case_study_area == None:
        cn = streets_gdf.geometry.unary_union.centroid
        buffer = cn.buffer(distance_from_center+distance_from_boundary) 
        streets_gdf = streets_gdf[streets_gdf.geometry.within(buffer)]
    else: streets_gdf = streets_gdf[streets_gdf.geometry.within(case_study_area.buffer(distance_from_boundary))]
    
    streets_gdf["from"] = None
    streets_gdf["to"] = None
    
    # creating the dataframes
    new_columns = ["highway","oneway", "maxspeed","name"]
    if len(dict_columns) > 0:
        for n, (key, value) in enumerate(dict_columns.items()):
            if (value != None): streets_gdf[new_columns[n]] = value
     
    standard_columns = ["geometry", "from", "to"]
    streets_gdf = streets_gdf[standard_columns + [new_columns[n] for n, i in enumerate(columns) if i is not None]]
    ix_geo = streets_gdf.columns.get_loc("geometry")+1
    
    # remove z coordinates, if any
    streets_gdf["geometry"] = streets_gdf.apply(lambda row: LineString([coor for coor in [row["geometry"].coords[i][0:2] for i in range(0, len(row["geometry"].coords))]]), axis = 1)
    streets_gdf["from"] = streets_gdf.apply(lambda row: row.geometry.coord[0], axis = 1)
    streets_gdf["to"] = streets_gdf.apply(lambda row: row.geometry.coord[-1], axis = 1)
        
    streets_gdf = streets_gdf.loc[streets_gdf["from"] != streets_gdf["to"]]
    unique_nodes_tmp = list(streets_gdf["to"].unique()) + list(streets_gdf["from"].unique())
    unique_nodes = list(set(unique_nodes_tmp))
    
    # assigning indexes
    streets_gdf.reset_index(inplace=True, drop=True)
    streets_gdf["edgeID"] = streets_gdf.index.values.astype(int) 
    
    #preparing nodes geodataframe
    nodes_data = pd.DataFrame.from_records(unique_nodes, columns=["x", "y"]).astype("float")
    geometry = [Point(xy) for xy in zip(nodes_data.x, nodes_data.y)]
    crs = {'init': 'epsg:' + str(epsg)}

    nodes_gdf = gpd.GeoDataFrame(nodes_data, crs=crs, geometry=geometry)
    nodes_gdf.reset_index(drop=True, inplace = True)
    nodes_gdf["nodeID"] = nodes_gdf.index.values.astype(int)
    nodes_gdf["coordinates"] = list(zip(nodes_gdf.x, nodes_gdf.y))

    edges_tmp = pd.merge(streets_gdf, nodes_gdf[["nodeID","coordinates"]], how="left", left_on="from", right_on="coordinates")
    edges_tmp.drop(edges_tmp[["coordinates"]], axis = 1, inplace = True)
    edges_tmp.rename(columns = {"nodeID":"u"}, inplace = True)
    
    edges_gdf = pd.merge(edges_tmp, nodes_gdf[["nodeID","coordinates"]], how="left", left_on="to", right_on="coordinates")
    edges_gdf = edges_gdf.drop(edges_gdf[["coordinates", "from", "to"]], axis = 1)
    edges_gdf = edges_gdf.rename(columns = {"nodeID":"v"})
    edges_gdf["length"] = gpd.GeoSeries(edges_gdf["geometry"].length) # computing length
    nodes_gdf.drop(["coordinates"], axis = 1, inplace = True)
    nodes_gdf['height'] = 2 # this will be used for 3d visibility analysis
    reset_index_street_network_gdfs(nodes_gdf, edges_gdf)    
    return nodes_gdf, edges_gdf
    

def reset_index_street_network_gdfs(nodes_gdf, edges_gdf):

    """
    The function simply reset the indexes of the two dataframes.
     
    Parameters
    ----------
    nodes_gdf: Point GeoDataFrame
        nodes (junctions) GeoDataFrame
    edges_gdf: LineString GeoDataFrame
        street segments GeoDataFrame
   
    Returns
    -------
    tuple of GeoDataFrames
    """
    
    edges_gdf = edges_gdf.rename(columns = {"u":"old_u", "v":"old_v"})
    nodes_gdf["old_nodeID"] = nodes_gdf.index.values.astype("int64")
    nodes_gdf = nodes_gdf.reset_index(drop = True)
    nodes_gdf["nodeID"] = nodes_gdf.index.values.astype("int64")
    
    edges_gdf = pd.merge(edges_gdf, nodes_gdf[["old_nodeID", "nodeID"]], how="left", left_on="old_u", right_on="old_nodeID")
    edges_gdf = edges_gdf.rename(columns = {"nodeID":"u"})
    edges_gdf = pd.merge(edges_gdf, nodes_gdf[["old_nodeID", "nodeID"]], how="left", left_on="old_v", right_on="old_nodeID")
    edges_gdf = edges_gdf.rename(columns = {"nodeID":"v"})

    edges_gdf.drop(["old_u", "old_nodeID_x", "old_nodeID_y", "old_v"], axis = 1, inplace = True)
    nodes_gdf.drop(["old_nodeID", "index"], axis = 1, inplace = True, errors = "ignore")
    edges_gdf = edges_gdf.reset_index(drop=True)
    edges_gdf["edgeID"] = edges_gdf.index.values.astype(int)

## Obtaining graphs ###############

def graph_fromGDF(nodes_gdf, edges_gdf, nodeID = "nodeID"):

    """
    From two GeoDataFrames (nodes and edges), it creates a NetworkX graph.
       
    Parameters
    ----------
    nodes_gdf: Point GeoDataFrame
        nodes (junctions) GeoDataFrame
    edges_gdf: LineString GeoDataFrame
        street segments GeoDataFrame
    nodeID: str
        please provide here the column name which indicates the node identifier column (if different from "nodeID")
        
    Returns
    -------
    NetworkX undirected Graph
    """

    nodes_gdf.set_index(nodeID, drop = False, inplace = True, append = False)
    del nodes_gdf.index.name
    if "key" in edges_gdf.columns: edges_gdf = edges_gdf[edges_gdf.key == 0].copy()
    
    G = nx.Graph()   
    G.add_nodes_from(nodes_gdf.index)
    attributes = nodes_gdf.to_dict()
    
    for attribute_name in nodes_gdf.columns:
        if type(nodes_gdf.iloc[0][attribute_name]) == list: 
            attribute_values = {k: v for k, v in attributes[attribute_name].items()}        
        # only add this attribute to nodes which have a non-null value for it
        else: attribute_values = {k: v for k, v in attributes[attribute_name].items() if pd.notnull(v)}
        nx.set_node_attributes(G, name=attribute_name, values=attribute_values)

    # add the edges and attributes that are not u, v, key (as they"re added
    # separately) or null
    for _, row in edges_gdf.iterrows():
        attrs = {}
        for label, value in row.iteritems():
            if (label not in ["u", "v"]) and (isinstance(value, list) or pd.notnull(value)):  attrs[label] = value
        G.add_edge(row["u"], row["v"], **attrs)
    
    return G


def multiGraph_fromGDF(nodes_gdf, edges_gdf, nodeID):

    """
    From two GeoDataFrames (nodes and edges), it creates a NetworkX MultiGraph.
    
    Parameters
    ----------
    nodes_gdf: Point GeoDataFrame
        nodes (junctions) GeoDataFrame
    edges_gdf: LineString GeoDataFrame
        street segments GeoDataFrame
    nodeID: str
        please provide here the column name which indicates the node identifier column (if different from "nodeID")
    
    Returns
    -------
    NetworkX MultiGraph
    """
    
    nodes_gdf.set_index(nodeID, drop = False, inplace = True, append = False)
    del nodes_gdf.index.name
    
    Mg = nx.MultiGraph()   
    Mg.add_nodes_from(nodes_gdf.index)
    attributes = nodes_gdf.to_dict()
    
    for attribute_name in nodes_gdf.columns:
        # only add this attribute to nodes which have a non-null value for it
        attribute_values = {k:v for k, v in attributes[attribute_name].items() if pd.notnull(v)}
        nx.set_node_attributes(Mg, name=attribute_name, values=attribute_values)

    # add the edges and attributes that are not u, v, key (as they"re added
    # separately) or null
    for _, row in edges_gdf.iterrows():
        attrs = {}
        for label, value in row.iteritems():
            if (label not in ["u", "v", "key"]) and (isinstance(value, list) or pd.notnull(value)):
                attrs[label] = value
        Mg.add_edge(row["u"], row["v"], key=row["key"], **attrs)
      
    return MG
    
## Building geo-dataframes for dual graph representation ###############

def dual_gdf(nodes_gdf, edges_gdf, epsg):

    """
    It creates two dataframes that are later exploited to generate the dual graph of a street network. The nodes_dual gdf contains edges 
    centroids; the edges_dual gdf, instead, contains links between the street segment centroids. Those dual edges link real street segments 
    that share a junction. The centroids are stored with the original edge edgeID, while the dual edges are associated with several
    attributes computed on the original street segments (distance between centroids, deflection angle).
    
    Parameters
    ----------
    nodes_gdf: Point GeoDataFrame
        nodes (junctions) GeoDataFrame
    edges_gdf: LineString GeoDataFrame
        street segments GeoDataFrame
    nodeID: str
        please provide here the column name which indicates the node identifier column (if different from "nodeID")
    epsg: int
        epsg of the area considered 

    Returns
    -------
    tuple of GeoDataFrames
    """
    
    if list(edges_gdf.index.values) != list(edges_gdf.edgeID.values): 
        edges_gdf.index =  edges_gdf.edgeID
        del edges_gdf.index.name
    
    # computing centroids                                       
    centroids_gdf = edges_gdf.copy()
    centroids_gdf["centroid"] = centroids_gdf["geometry"].centroid
    centroids_gdf["intersecting"] = None
    
    ix_u, ix_v = centroids_gdf.columns.get_loc("u")+1, centroids_gdf.columns.get_loc("v")+1
    ix_edgeID = centroids_gdf.columns.get_loc("edgeID")+1
         
    # find_intersecting segments and storing them in the centroids gdf
    centroids_gdf["intersecting"] = centroids_gdf.apply(lambda row: list(centroids_gdf.loc[(centroids_gdf["u"] == row["u"])|(centroids_gdf["u"] == row["v"])|
                                                    (centroids_gdf["v"] == row["v"])|(centroids_gdf["v"] == row["u"])].index), axis=1)
            
    # creating vertexes representing street segments (centroids)
    centroids_data = centroids_gdf[["edgeID", "intersecting", "length"]]
    if epsg == None: crs = nodes_gdf.crs
    else: crs = {'init': 'epsg:' + str(epsg)}
    nodes_dual = gpd.GeoDataFrame(centroids_data, crs=crs, geometry=centroids_gdf["centroid"])
    nodes_dual["x"], nodes_dual["y"] = [x.coords.xy[0][0] for x in centroids_gdf["centroid"]], [y.coords.xy[1][0] for y in centroids_gdf["centroid"]]
    nodes_dual.index =  nodes_dual.edgeID
    del nodes_dual.index.name
    
    # creating fictious links between centroids
    edges_dual = pd.DataFrame(columns=["u","v", "geometry", "length"])
    ix_length = nodes_dual.columns.get_loc("length")+1
    ix_intersecting = nodes_dual.columns.get_loc("intersecting")+1
    ix_geo = nodes_dual.columns.get_loc("geometry")+1

    # connecting nodes which represent street segments share a linked in the actual street network   
    processed = []
    for row in nodes_dual.itertuples():                                           
        # intersecting segments:  # i is the edgeID                                      
        for intersecting in row[ix_intersecting]:
            if ((row.Index == intersecting) | ((row.Index, intersecting) in processed) | ((intersecting, row.Index) in processed)): continue
            length_intersecting =  nodes_dual.loc[intersecting]["length"]
            distance = (row[ix_length]+length_intersecting)/2
        
            # adding a row with u-v, key fixed as 0, Linestring geometry 
            # from the first centroid to the centroid intersecting segment 
            ls = LineString([row[ix_geo], nodes_dual.loc[intersecting]["geometry"]])
            edges_dual.loc[-1] = [row.Index, intersecting, ls, distance] 
            edges_dual.index = edges_dual.index + 1
            processed.append((row.Index, intersecting))
            
    edges_dual = edges_dual.sort_index(axis=0)
    edges_dual = gpd.GeoDataFrame(edges_dual[["u", "v", "length"]], crs=crs, geometry=edges_dual["geometry"])
    
    # setting angle values in degrees and radians
    edges_dual["deg"] = edges_dual.apply(lambda row: angle_line_geometries(edges_gdf.loc[row["u"]].geometry, edges_gdf.loc[row["v"]].geometry, degree = True, angular_change = True), axis = 1)
    edges_dual["rad"] = edges_dual.apply(lambda row: angle_line_geometries(edges_gdf.loc[row["u"]].geometry, edges_gdf.loc[row["v"]].geometry, degree = False, angular_change = True), axis = 1)
        
    return nodes_dual, edges_dual

def dual_graph_fromGDF(nodes_dual, edges_dual):

    """
    The function generates a NetworkX graph from dual-nodes and -edges GeoDataFrames.
            
    Parameters
    ----------
    nodes_dual: Point GeoDataFrame
        the GeoDataFrame of the dual nodes, namely the street segments' centroids
    edges_dual: LineString GeoDataFrame
        the GeoDataFrame of the dual edges, namely the links between street segments' centroids 
        
    Returns
    -------
    NetworkX Graph
    """
   
    nodes_dual.set_index("edgeID", drop = False, inplace = True, append = False)
    del nodes_dual.index.name
    edges_dual.u = edges_dual.u.astype(int)
    edges_dual.v = edges_dual.v.astype(int)
    
    Dg = nx.Graph()   
    Dg.add_nodes_from(nodes_dual.index)
    attributes = nodes_dual.to_dict()
    
    for attribute_name in nodes_dual.columns:
        # only add this attribute to nodes which have a non-null value for it
        if attribute_name == "intersecting": continue
        attribute_values = {k:v for k, v in attributes[attribute_name].items() if pd.notnull(v)}
        nx.set_node_attributes(Dg, name=attribute_name, values=attribute_values)

    # add the edges and attributes that are not u, v, key (as they"re added
    # separately) or null
    for _, row in edges_dual.iterrows():
        attrs = {}
        for label, value in row.iteritems():
            if (label not in ["u", "v"]) and (isinstance(value, list) or pd.notnull(value)):
                attrs[label] = value
        Dg.add_edge(row["u"], row["v"], **attrs)

    return Dg

def dual_id_dict(dict_values, G, node_attribute):

    """
    It could be used when one deals with a dual graph and wants to link analyses conducted on this representation to the
    the primal graph. For instance, it takes the dictionary containing the betweennes-centrality values of the
    nodes in the dual graph, and associates these variables to the corresponding edgeID.
    
    Parameters
    ----------
    dict_values: dictionary 
        it should be in the form {nodeID: value} where values is a measure that has been computed on the graph, for example
    G: networkx graph
        the graph that was used to compute or to assign values to nodes or edges
    node_attribute: string
        the attribute of the node to link to the edges GeoDataFrame
    
    Returns
    -------
    dictionary
    """
    
    view = dict_values.items()
    ed_list = list(view)
    ed_dict = {}
    for p in ed_list: ed_dict[G.nodes[p[0]][node_attribute]] = p[1] # attribute and measure
        
    return ed_dict

    

 