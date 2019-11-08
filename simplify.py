import pandas as pd, numpy as np, geopandas as gpd
import functools
import math
from math import sqrt

from scipy import sparse
from scipy.sparse import linalg
import pysal as ps

from shapely.geometry import Point, LineString, Polygon, MultiPolygon, mapping, MultiLineString
from shapely.ops import cascaded_union, linemerge, nearest_points

import ast
import utilities as uf
import street_network_functions as snf
pd.set_option('precision', 10)
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

# math functions for angle computations
# from Abhinav Ramakrishnan answer in https://stackoverflow.com/a/28261304/7375309


def euclidean_distance(xs, ys, xt, yt):
    """ xs stands for x source and xt for x target """
    return sqrt((xs - xt)**2 + (ys - yt)**2)


def perpendicular(geolineA, geolineB):
    
    angle = uf.ang_geoline(geolineA, geolineB, degree = True)
    if ((angle <= 110) & (angle >= 70)): return True
    line_coordsA = list(geolineA.coords)
    line_coordsB = list(geolineB.coords)
    
    originA, endA = Point(line_coordsA[0]), Point(line_coordsA[-1])
    originB, endB = Point(line_coordsB[0]), Point(line_coordsB[-1])
    
    distOO = originA.distance(originB)
    distOE = originA.distance(endB)
    distEO = endA.distance(originB)
    distEE = endA.distance(endB)
    dist = [distOO, distOE, distEO, distEE]
    
    if (originA == endB) | (min(dist) == distOE): line_coordsB.reverse()
    elif (endA == endB) | (min(dist) == distEE):
        line_coordsA.reverse()
        line_coordsB.reverse()
    elif (endA == originB) | (min(dist) == distEO): line_coordsA.reverse()
    elif (originA == originB) | (min(dist) == distOO): pass       
    
    geolineA = LineString([coor for coor in line_coordsA[0:2]])
    geolineB = LineString([coor for coor in line_coordsB[0:2]])
    angle = uf.ang_geoline(geolineA, geolineB, degree = True)
    if ((angle <= 110) & (angle >= 70)): return True
    else: return False

def parallel(geolineA, geolineB, hard = False):
    
    angle = uf.ang_geoline(geolineA, geolineB, degree = True)
    if ((angle <= 20) | (angle >= 160)): return True
        
    line_coordsA = list(geolineA.coords)
    line_coordsB = list(geolineB.coords)
    
    if ((len(line_coordsA) == 2) | (len(line_coordsB) == 2)): return False
    
    spA = Point(line_coordsA[0])
    spB = Point(line_coordsB[0])
    epB = Point(line_coordsB[-1])
    if spA.distance(spB) > spA.distance(epB): line_coordsB.reverse()
    
    if hard == False:
        # remove 1st coordinates (A,B)
        geolineA = LineString([coor for coor in line_coordsA[1:]])
        geolineB = LineString([coor for coor in line_coordsB[1:]])
        angle = uf.ang_geoline(geolineA, geolineB, degree = True)
        if ((angle <= 20) | (angle >= 160)): return True
        
        # remove 1st (A) and last (B)
        geolineB = LineString([coor for coor in line_coordsB[:-1]])
        angle = uf.ang_geoline(geolineA, geolineB, degree = True)
        if ((angle <= 20) | (angle >= 160)): return True
        
        # remove last (A) and 1st (B)
        geolineA = LineString([coor for coor in line_coordsA[:-1]])
        geolineB = LineString([coor for coor in line_coordsB[1:]])
        angle = uf.ang_geoline(geolineA, geolineB, degree = True)
        if ((angle <= 20) | (angle >= 160)): return True
        
        # remove last coordinates (A, B)
        geolineA = LineString([coor for coor in line_coordsA[:-1]])
        geolineB = LineString([coor for coor in line_coordsB[:-1]])
        angle = uf.ang_geoline(geolineA, geolineB, degree = True)
        if ((angle <= 20) | (angle >= 160)): return True
        
        if ((len(line_coordsA) == 3) | (len(line_coordsB) == 3)): return False
        geolineA = LineString([coor for coor in line_coordsA[1:-1]])
        geolineB = LineString([coor for coor in line_coordsB[1:-1]])

        angle = uf.ang_geoline(geolineA, geolineB, degree = True)
        if ((angle <= 20) | (angle >= 160)): return True
    return False


def simplify_dual_lines_junctions(nodes_gdf, edges_gdf, update_counts = False):
    
    edges_gdf = edges_gdf.copy()
    nodes_gdf = nodes_gdf.copy()
    edges_gdf['name'][edges_gdf.name.isnull()] = None
    o_edges = edges_gdf.copy()
    
    ix_geo = edges_gdf.columns.get_loc("geometry")+1  
    ix_u = edges_gdf.columns.get_loc("u")+1
    ix_v = edges_gdf.columns.get_loc("v")+1
    ix_name = edges_gdf.columns.get_loc("name")+1
    ix_ID = nodes_gdf.columns.get_loc("nodeID")+1   
    
    nodes_gdf.set_index('nodeID', drop = False, inplace = True, append = False)
    del nodes_gdf.index.name
    edges_gdf.set_index('streetID', drop = False, inplace = True, append = False)
    del edges_gdf.index.name
    
    oldID = False
    if 'oldIDs' in nodes_gdf.columns: oldID = True
    else: nodes_gdf['oldIDs'] =  [[t] for t in nodes_gdf.nodeID]
    
    
    ################################ FROM NODES TO NODES      
    
    print('Simplifying intersections: first part -------------------------- ')
    processed = []

    to_do = [85496, 85497, 85505, 85507, 85513]    
    for row in o_edges.itertuples():
#         if (row.Index in to_do) == False: continue
        if row.Index in processed: continue  
    
        for r in [ix_u, ix_v]:
            found = False
            pm = o_edges[(o_edges['u'] == row[r]) | (o_edges['v'] == row[r])].copy()
            pm.drop(row.Index, axis = 0, inplace = True)
            pm = pm[~pm.index.isin(processed)]

            for rowC in pm.itertuples(): 
                if (iscontinuation(row.Index, rowC.Index, edges_gdf) == False) | (rowC[ix_geo].length > row[ix_geo].length):
                    pm.drop(rowC.Index, axis = 0, inplace = True)
                    continue

            if len(pm) == 0: continue
            if r == ix_u: 
                direction = 'v'
                to_reach = row[ix_v]    
            else: 
                direction = 'u'
                to_reach = row[ix_u]           
                    
            for rowC in pm.itertuples():
                if rowC[ix_u] == row[r]: search = rowC[ix_v]  
                else: search = rowC[ix_u]

                nodes_encountered = [search]
                lines_traversed = [rowC[ix_geo]]
                lines = [rowC.Index]
                next_line = False
                last_line = rowC.Index

                while (not found) & (not next_line):
                    pmC = o_edges[(o_edges['u'] == search) | (o_edges['v'] == search)].copy()      
                    pmC.drop([last_line, row.Index], axis = 0, inplace = True, errors = 'ignore')
                    pmC = pmC[~pmC.index.isin(processed)]

                    for rowCC in pmC.itertuples():
                        if iscontinuation(last_line, rowCC[0], edges_gdf) == False: pmC.drop(rowCC[0], axis = 0, inplace = True)

                    if len(pmC) == 0:
                        next_line = True
                        break

                    if len(pmC) > 1:
                        pmC['angle'] = 0.0
                        for s in pmC.itertuples():
                            angle = uf.ang_geoline(edges_gdf.loc[last_line].geometry, s[ix_geo], deflection = True, degree = True)
                            pmC.at[s[0], 'angle'] = angle
                        pmC.sort_values(by = 'angle', ascending = True, inplace = True)    

                    u = pmC.iloc[0]['u']
                    v = pmC.iloc[0]['v']

                    if u == search: 
                        search = pmC.iloc[0]['v']
                        other = pmC.iloc[0]['u']
                    else: 
                        search = pmC.iloc[0]['u']
                        other = pmC.iloc[0]['v']

                    distA = nodes_gdf.loc[search].geometry.distance(nodes_gdf.loc[to_reach].geometry)
                    distB = nodes_gdf.loc[other].geometry.distance(nodes_gdf.loc[to_reach].geometry)

                    if (search in nodes_encountered) | (distB < distA):           
                        next_line = True
                        continue
                    elif search == to_reach:
                        lines_traversed.append(pmC.iloc[0].geometry)
                        lines.append(pmC.iloc[0].name)
                        found = True
                        break
                    else: 
                        nodes_encountered.append(search)
                        lines_traversed.append(pmC.iloc[0].geometry)
                        lines.append(pmC.iloc[0].name)
                        last_line = pmC.iloc[0].name

                if next_line == True: continue
                else: break

            if found == False: continue
            u, v, geo = row[ix_u], row[ix_v], row[ix_geo]    
            merged_line = uf.merge_lines(lines_traversed)

            if (geo.length*1.40 < merged_line.length) | (geo.length > merged_line.length*1.40): continue
            if (geo.centroid.distance(merged_line.centroid) > 30.0): continue

            center_line = uf.center_line(geo, merged_line)
            processed = processed + lines
            processed.append(row.Index)
            if len(edges_gdf.loc[lines][edges_gdf.pedestrian == 1]) > 0: edges_gdf.at[row.Index, 'pedestrian'] = 1
            if direction == 'u': nodes_encountered.reverse()
            interpolate(u, v, center_line, nodes_encountered, lines, nodes_gdf, edges_gdf, row.Index, update_counts = True)
            edges_gdf.drop(lines, axis = 0, inplace = True) 
            break
            
    nodes_gdf, edges_gdf = snf.correct_edges(nodes_gdf, edges_gdf)
    nodes_gdf, edges_gdf = snf.clean_network(nodes_gdf, edges_gdf, 
                                             update_counts = update_counts, dead_ends = True, detect_islands = False)
    
    return(nodes_gdf, edges_gdf)

def simplify_complex_junctions(nodes_gdf, edges_gdf, update_counts = True):
    
    "-----------------------------"
    print('Simplifying intersections: second part -------------------------- Triangle-Like-Junctions')
    
    edges_gdf = edges_gdf.copy()
    nodes_gdf = nodes_gdf.copy()
    edges_gdf['name'][edges_gdf.name.isnull()] = None
    o_edges = edges_gdf.copy()
    
    ix_geo = edges_gdf.columns.get_loc("geometry")+1  
    ix_u = edges_gdf.columns.get_loc("u")+1
    ix_v = edges_gdf.columns.get_loc("v")+1
    ix_name = edges_gdf.columns.get_loc("name")+1
    ix_ID = nodes_gdf.columns.get_loc("nodeID")+1   
    
    nodes_gdf.set_index('nodeID', drop = False, inplace = True, append = False)
    del nodes_gdf.index.name
    edges_gdf.set_index('streetID', drop = False, inplace = True, append = False)
    del edges_gdf.index.name
    
    oldID = False
    if 'oldIDs' in nodes_gdf.columns: oldID = True
    else: nodes_gdf['oldIDs'] =  [[t] for t in nodes_gdf.nodeID]
    if list(nodes_gdf.index.values) != list(nodes_gdf.nodeID.values): nodes_gdf.index = nodes_gdf.nodeID
    processed = []
    
    for n in nodes_gdf.itertuples():
        tmp =  edges_gdf[(edges_gdf['u'] == n[ix_ID]) | (edges_gdf['v'] == n[ix_ID])].copy()
        found = False
        
        for row in tmp.itertuples():
            if row.Index in processed: continue

            for rowC in tmp.itertuples():
                if (row.Index == rowC.Index) | (rowC.Index in processed) : continue

                if row[ix_u] == rowC[ix_u]: # the last one is 'v'
                    v1, v2 = ix_v, ix_v
                    last_vertex, code = -1, 'v'
                    
                elif row[ix_u] == rowC[ix_v]: # the last one is 'u'
                    v1, v2 = ix_v, ix_u
                    last_vertex, code = -1, 'v'
                
                elif row[ix_v] == rowC[ix_u]: # the last one is 'u'
                    v1, v2 = ix_u, ix_v
                    last_vertex, code = 0, 'u'
                    
                elif row[ix_v] == rowC[ix_v]: # the last one is 'u'
                    v1, v2 = ix_u, ix_u
                    last_vertex, code = 0, 'u'
                    
                else: continue
                   
                tmpC =  edges_gdf[((edges_gdf['u'] == row[v1]) & (edges_gdf['v'] == rowC[v2])) | 
                                    ((edges_gdf['u'] == rowC[v2]) & (edges_gdf['v'] == row[v1]))].copy()
                    
                if len(tmpC) == 0: continue
                connecting = tmpC.iloc[0]
                
                u, v, uC, vC = row[ix_u], row[ix_v], rowC[ix_u], rowC[ix_v]
                geo, geoC = row[ix_geo], rowC[ix_geo]
                diff = abs(geo.length-geoC.length)    
                
                # break when:
                if (geo.length > 200) | (connecting.geometry.length > 200) | (geoC.length > 200): break
                if ((row[ix_name] != rowC[ix_name]) & (rowC[ix_name] != connecting['name']) &
                    (row[ix_name] != connecting['name']) & (row[ix_name] != None) &
                    (rowC[ix_name] != None) & (connecting['name'] != None) & (geo.length > 40) & (geoC.length > 40)): break
                
                # continue when
                if (((row[ix_name] != rowC[ix_name]) & ((row[ix_name] != None) &  (rowC[ix_name] != None))) 
                & (geo.length > 80)): continue
                if ((row[ix_name] != rowC[ix_name]) & ((rowC[ix_name] == connecting['name']) |
                    (row[ix_name] == connecting['name']))): continue
                if (connecting.geometry.length > (geo.length + geoC.length)*1.10): continue  
                if (((row[ix_name] == rowC[ix_name]) & (rowC[ix_name] == connecting['name'])) &
                    ((abs(geo.length-connecting.geometry.length) < abs(geo.length-geoC.length))
                     | (abs(geoC.length-connecting.geometry.length) < abs(geo.length-geoC.length)))): continue
                
                if (((diff >geo.length*0.75) | (diff >geoC.length*0.75)) & (row[ix_name] == rowC[ix_name])): continue
                elif (((diff >geo.length*0.35) | (diff>geoC.length*0.35)) & (row[ix_name] != rowC[ix_name])): continue
                
                if edges_gdf.loc[rowC.Index]['pedestrian'] == 1: edges_gdf.at[row.Index, 'pedestrian'] = 1
                edges_gdf.drop(rowC.Index, axis = 0, inplace = True)
                
                cl =  uf.center_line(geo, geoC)
                intersection = cl.intersection(connecting.geometry)
                ix_node = nodes_gdf.index.max()+1
                nodes_gdf.loc[ix_node] = nodes_gdf.loc[row[v1]] 
                nodes_gdf.at[ix_node, 'nodeID'] = ix_node
                
                ix_edge = edges_gdf.index.max()+1
                edges_gdf.loc[ix_edge] = edges_gdf.loc[connecting.name]
                edges_gdf.at[ix_edge, 'streetID'] = ix_edge
                
                edges_gdf.at[row.Index, code] = ix_node

                
                if intersection.geom_type == 'Point':
                    last = intersection.coords[0]
                    line = split_line_interpolation(intersection, cl)[0]
                    nodes_gdf.at[ix_node, 'geometry'] = intersection
                    
                    if code == 'u': edges_gdf.at[row.Index,'geometry'] = line[1]
                    else: edges_gdf.at[row.Index,'geometry'] = line[0]
                    
                    line = split_line_interpolation(intersection, connecting.geometry)[0]
                    edges_gdf.at[connecting.name, 'geometry'] = line[0]
                    edges_gdf.at[connecting.name, 'v'] = ix_node
                    edges_gdf.at[ix_edge, 'u'] = ix_node
                    edges_gdf.at[ix_edge, 'geometry'] = line[1]

                else: # no intersection
                    last = list(cl.coords)[last_vertex]
                    nodes_gdf.at[ix_node, 'geometry'] = Point(last)
                    edges_gdf.at[row.Index,'geometry'] = cl

                    geolineA = LineString([coor for coor in [connecting.geometry.coords[0], last]])
                    geolineB = LineString([coor for coor in [last, connecting.geometry.coords[-1]]])
                    edges_gdf.at[connecting.name, 'geometry'] = geolineA
                    edges_gdf.at[ix_edge, 'geometry'] = geolineB
                    edges_gdf.at[connecting.name, 'v'] = ix_node
                    edges_gdf.at[ix_edge, 'u'] = ix_node

                if update_counts == True: 
                    edges_gdf.at[row.Index, 'counts'] = o_edges.loc[row.Index].counts + o_edges.loc[rowC.Index].counts 
                    edges_gdf.at[ix_edge, 'counts'] = connecting.counts 
                
                processed = processed + [row.Index, rowC.Index]
                nodes_gdf.at[ix_node, 'x'] = last[0]
                nodes_gdf.at[ix_node, 'y'] = last[1]
                
                if oldID == True:                  
                    oldIDs = list(nodes_gdf.loc[[row[v1], rowC[v2]]]['oldIDs'])
                    oldIDs = [item for sublist in oldIDs for item in sublist]
                    
                else: oldIDs = list(nodes_gdf.loc[[row[v1], rowC[v2]]]['nodeID'])
                nodes_gdf.at[ix_node, 'oldIDs'] = oldIDs
                found = True
                break
                                    
            if found == True: break
                        
    nodes_gdf, edges_gdf = snf.correct_edges(nodes_gdf, edges_gdf)
    nodes_gdf, edges_gdf = snf.clean_network(nodes_gdf, edges_gdf, 
                                             update_counts = update_counts, dead_ends = True, detect_islands = False)

    return(nodes_gdf, edges_gdf)

def extract_centroids(nodes_gdf, edges_gdf, radius = 10):   
    
    edges_gdf, nodes_gdf = edges_gdf.copy(), nodes_gdf.copy() 
    
    buffered_nodes = nodes_gdf.buffer(radius).unary_union
    if isinstance(buffered_nodes, Polygon): buffered_nodes = [buffered_nodes]
        
    buffered_nodes_geoS = gpd.GeoSeries(list(buffered_nodes))
    buffered_nodes_df =  pd.concat([buffered_nodes_geoS.rename('geometry'), pd.Series(buffered_nodes_geoS.index).rename('code')], axis=1)

    buffered_nodes_gdf = gpd.GeoDataFrame(buffered_nodes_df, geometry = buffered_nodes_df.geometry)
    buffered_nodes_gdf['area']= buffered_nodes_gdf['geometry'].area
    buffered_nodes_gdf['centroid'] = buffered_nodes_gdf.geometry.centroid
    
    clusters_gdf = buffered_nodes_gdf[buffered_nodes_gdf["area"] > (radius*radius*3.14159)]
    clusters_gdf['x'], clusters_gdf['y'] = (clusters_gdf.geometry.centroid.x, clusters_gdf.geometry.centroid.y)
    clusters_gdf.index += nodes_gdf.index.max()+1
    clusters_gdf['code'] = clusters_gdf.index
    
    nodes_gdf['cluster'] = None
    ix_geo_bn = clusters_gdf.columns.get_loc("geometry")+1
    ix_code = clusters_gdf.columns.get_loc("code")+1
    ix_geo = nodes_gdf.columns.get_loc("geometry")+1
    
    sindex = clusters_gdf.sindex    
    # set cluster column values
    for row in nodes_gdf.itertuples(): 
        geo = row[ix_geo]
        pm_index = list(sindex.intersection(geo.buffer(5).bounds)) 
        if len(pm_index) == 0: continue
        pm = clusters_gdf.iloc[pm_index]
        for rowC in pm.itertuples():
            if geo.within(rowC[ix_geo_bn]): nodes_gdf.at[row.Index,'cluster'] = rowC[ix_code]
    
    buffers_gdf = clusters_gdf.drop('centroid', axis = 1)
    geometry = clusters_gdf['centroid']
    data = clusters_gdf.drop(['centroid', 'geometry'], axis=1)
    clusters_gdf = gpd.GeoDataFrame(data, crs=nodes_gdf.crs, geometry=geometry)
    edges_gdf = assign_cluster_edges(nodes_gdf, edges_gdf)
    
    return(nodes_gdf, edges_gdf, clusters_gdf, buffers_gdf)
    
def assign_cluster_edges(nodes_gdf, edges_gdf):
    
    edges_gdf.drop(['nodeID_x', 'nodeID_y','clus_uR', 'clus_vR', 'clus_u', 'clus_v'], axis = 1, inplace = True, errors = 'ignore')
    edges_gdf = pd.merge(edges_gdf, nodes_gdf[['cluster', 'nodeID']], how = 'left', left_on= "u", right_on = "nodeID")
    edges_gdf = edges_gdf.rename(columns = {'cluster':'clus_u'})
    edges_gdf = pd.merge(edges_gdf, nodes_gdf[['cluster', 'nodeID']], how = 'left', left_on= "v", right_on = "nodeID")
    edges_gdf = edges_gdf.rename(columns = {'cluster':'clus_v'})  
    edges_gdf.set_index('streetID', drop = False, append = False, inplace = True)
    del edges_gdf.index.name
    
    edges_gdf['clus_uR'], edges_gdf['clus_vR'] = None, None
    ix_clus_u, ix_clus_v  = edges_gdf.columns.get_loc("clus_u")+1, edges_gdf.columns.get_loc("clus_v")+1
    ix_clus_uR, ix_clus_vR = edges_gdf.columns.get_loc("clus_uR")+1, edges_gdf.columns.get_loc("clus_vR")+1
   
    # assigning cluster
    tmp = edges_gdf[(edges_gdf['clus_u'].isnull()) | (edges_gdf['clus_v'].isnull())].copy()
    for row in tmp.itertuples():
        if row[ix_clus_u] is None:
            result = next_cluster(nodes_gdf, edges_gdf, row.Index, 'u')
            goal = result[0]
            edges_gdf.at[row.Index, 'clus_uR'] = goal
        if row[ix_clus_v] is None:
            result = next_cluster(nodes_gdf, edges_gdf, row.Index, 'v')
            goal = result[0]
            edges_gdf.at[row.Index, 'clus_vR'] = goal
    
    edges_gdf.drop(['nodeID_x', 'nodeID_y'], axis = 1, inplace = True, errors = 'ignore')       
    return(edges_gdf)

def next_cluster(nodes_gdf, edges_gdf, ix_line, search_dir):
    
    ix_geo = edges_gdf.columns.get_loc("geometry")+1
    ix_name = edges_gdf.columns.get_loc("name")+1
    ix_u = edges_gdf.columns.get_loc("u")+1
    ix_v = edges_gdf.columns.get_loc("v")+1
    
    u, v = edges_gdf.loc[ix_line]['u'], edges_gdf.loc[ix_line]['v']
    line = edges_gdf.loc[ix_line].geometry
    name = edges_gdf.loc[ix_line]['name']
    line_coords = list(line.coords)
    
    if search_dir == 'v': 
        coming_from = v
        other_node = u
        pm = edges_gdf[(edges_gdf.u == v) | (edges_gdf.v == v)].copy()
    else: 
        line_coords.reverse()
        coming_from = u
        other_node = v
        pm = edges_gdf[(edges_gdf.u == u) | (edges_gdf.v == u)].copy()
     
    pm.drop(ix_line, axis = 0, inplace = True)
    nodes_encountered = []
    lines_traversed = []
    last_line = ix_line

    found = False
    while (found == False):
        if len(pm) == 0: 
            found = True
            return(None, None, None, None, None)
      
        if len(pm) > 1:
            pm['angle'] = 0.0
            for p in pm.itertuples():
                    angle = uf.ang_geoline(edges_gdf.loc[last_line].geometry, p[ix_geo], deflection = True, degree = True)
                    pm.at[p[0], 'angle'] = angle
            pm.sort_values(by = 'angle', ascending = True, inplace = True)    
            
        for p in pm.itertuples():
            if iscontinuation(last_line, p[0], edges_gdf) == False:
                pm.drop(p[0], axis = 0, inplace = True)
                continue
            
            else:
                uCP, vCP = p[ix_u], p[ix_v]
                
                if uCP == coming_from:
                    cluster = nodes_gdf.loc[vCP].cluster
                    coming_from = vCP
                    distance_to = nodes_gdf.loc[vCP].geometry.distance(nodes_gdf.loc[other_node].geometry)
                    distance_from = nodes_gdf.loc[uCP].geometry.distance(nodes_gdf.loc[other_node].geometry)
                    if (vCP in nodes_encountered) | (distance_to < distance_from):
                        pm = pm[0:0]
                        break
                else: 
                    cluster = nodes_gdf.loc[uCP].cluster
                    coming_from = uCP
                    distance_to = nodes_gdf.loc[uCP].geometry.distance(nodes_gdf.loc[other_node].geometry)
                    distance_from = nodes_gdf.loc[vCP].geometry.distance(nodes_gdf.loc[other_node].geometry)
                    if (uCP in nodes_encountered) | (distance_to < distance_from):
                        pm = pm[0:0]
                        break
                                    
                if cluster is None:
                    lines_traversed.append(p[0])
                    last_line = p[0]

                    if vCP == coming_from:
                        pm = edges_gdf[(edges_gdf.u == vCP) | (edges_gdf.v == vCP) ].copy()
                        nodes_encountered.append(uCP) 
                        line_coords = line_coords + list(p[ix_geo].coords)
                    else:
                        pm = edges_gdf[(edges_gdf.u == uCP) | (edges_gdf.v == uCP)].copy()
                        nodes_encountered.append(vCP)
                        tmp = list(p[ix_geo].coords)
                        tmp.reverse()
                        line_coords = line_coords + tmp
                    break
                
                else:
                    found = True
                    lines_traversed.append(p[0])
                    
                    if vCP == coming_from:
                        nodes_encountered.append(uCP)
                        last_node = vCP
                        line_coords = line_coords + list(p[ix_geo].coords)
                    else: 
                        nodes_encountered.append(vCP)
                        last_node = uCP
                        tmp = list(p[ix_geo].coords)
                        tmp.reverse()
                        line_coords = line_coords + tmp
                    break
    
    merged_line = LineString([coor for coor in line_coords])   
    return(cluster, merged_line, lines_traversed, nodes_encountered, last_node)
        
def center_line_cluster(line_geo, line_geoC, nodes_gdf, clusters_gdf, cluster_from, cluster_to, one_cluster = False): 
    
    if one_cluster == True: coord_from = (nodes_gdf.loc[cluster_from]['x'], nodes_gdf.loc[cluster_from]['y'])
    else: coord_from = (clusters_gdf.loc[cluster_from]['x'], clusters_gdf.loc[cluster_from]['y'])
    
    coord_to =  (clusters_gdf.loc[cluster_to]['x'], clusters_gdf.loc[cluster_to]['y'])
    line_coordsA = list(line_geo.coords)
    line_coordsB = list(line_geoC.coords)
    
    # no need to reverse lines, as they should arrive already in the same order      
    # different number of vertexes, connect the line
    while len(line_coordsA) > len(line_coordsB):
        index = int(len(line_coordsA)/2)
        del line_coordsA[index]
    while len(line_coordsB) > len(line_coordsA):
        index = int(len(line_coordsB)/2)
        del line_coordsB[index]      
    
    new_line = line_coordsA
    for n, i in enumerate(line_coordsA):
        link = LineString([coor for coor in [line_coordsA[n], line_coordsB[n]]])
        np = link.centroid.coords[0]           
        new_line[n] = np
        
    new_line[0] = coord_from
    new_line[-1] = coord_to
    center_line = LineString([coor for coor in new_line])           
        
    return(center_line)

def center_line_cluster_four(list_lines, nodes_gdf, clusters_gdf, cluster_from, cluster_to, one_cluster = False): 
    
    coord_from = (clusters_gdf.loc[cluster_from]['x'], clusters_gdf.loc[cluster_from]['y'])
    coord_to =  (clusters_gdf.loc[cluster_to]['x'], clusters_gdf.loc[cluster_to]['y'])
    
    list_coords = []
    for i in list_lines: list_coords.append(list(i.coords))
    
    # no need to reverse lines, as they should arrive already in the same order      
    # different number of vertexes, connect the line
    
    for line in list_coords:
        for lineC in list_coords:
            if line == lineC: continue               
            while len(line) > len(lineC):
                index = int(len(line)/2)
                del line[index]    

    new_line = list_coords[0]
    for n, i in enumerate(list_coords[0]):       
        pairs = [coor[n] for coor in list_coords]
        pairs = list(set(pairs))
        maxDistance = 0
        for point in pairs:
            for pointC in pairs:
                if point == pointC: continue
                distance = Point(point).distance(Point(pointC))
                if distance > maxDistance:
                    furthest = [point, pointC]
                    maxDistance = distance
                    
        if len(pairs) == 2:
            link = LineString([coor for coor in [pairs[0], pairs[1]]])
        
        elif len(pairs) == 3:
            second = [x for x in pairs if x not in furthest]
            link = LineString([coor for coor in [furthest[0], second[0], furthest[1]]])
        else:
            # find second
            maxDistance = 0.0
            last = None
            
            for point in pairs:
                if point in furthest: continue
                distance = Point(point).distance(Point(furthest[0]))
                if distance > maxDistance:
                    maxDistance = distance
                    last = point   
                    
            second = [x for x in pairs if x not in furthest]
            second.remove(last)
            link = LineString([coor for coor in [furthest[0], second[0], last, furthest[1]]])
        np = link.centroid.coords[0]      
        new_line[n] = np
    
    
    new_line[0] = coord_from
    new_line[-1] = coord_to
    center_line = LineString([coor for coor in new_line])           
        
    return(center_line)



def split_line_interpolation(point, line_geo):
    
    old_list = list(line_geo.coords)
    starting_point = Point(old_list[0])
    np = nearest_points(point, line_geo)[1]
    distance_start = line_geo.project(np)
    
    new_line_A = []
    new_line_B = []

    if(len(old_list)) == 2:
        new_line_A = [old_list[0],  np.coords[0]]
        new_line_B = [np.coords[0], old_list[-1]]
        glineA = LineString([coor for coor in new_line_A])
        glineB = LineString([coor for coor in new_line_B])

    else:
        new_line_A.append(old_list[0])
        new_line_B.append(np.coords[0])

        for n, i in enumerate(old_list):
            if (n == 0) | (n == len(old_list)-1): continue
            if line_geo.project(Point(i)) < distance_start: new_line_A.append(i)
            else: new_line_B.append(i)

        new_line_A.append(np.coords[0])
        new_line_B.append(old_list[-1])
        glineA = LineString([coor for coor in new_line_A])
        glineB = LineString([coor for coor in new_line_B])
    
    return((glineA, glineB), np)

def interpolate(first_node, last_node, center_line, list_nodes, list_lines, nodes_gdf, edges_gdf, ix_line, update_counts = False):
   
    gline = center_line    
    new_index = ix_line
    for counter, node in enumerate(list_nodes):
        point = nodes_gdf.loc[node].geometry
        result, np = split_line_interpolation(point, gline)
              
        # adjusting node coordinates
        nodes_gdf.at[node, 'x'] = np.coords[0][0]
        nodes_gdf.at[node, 'y'] = np.coords[0][1]
        nodes_gdf.at[node, 'geometry'] = np
        
        #first part of the segment
        if counter == 0: edges_gdf.at[new_index, 'u'] = first_node
        edges_gdf.at[new_index, 'geometry'] = result[0]
        edges_gdf.at[new_index, 'v'] = node
        if update_counts == True: 
            edges_gdf.at[new_index, 'counts'] = edges_gdf.loc[ix_line].counts + edges_gdf.loc[list_lines[counter]].counts
        
        # second part of the segment
        new_index = max(edges_gdf.index)+1
        edges_gdf.loc[new_index] = edges_gdf.loc[ix_line]
        edges_gdf.at[new_index, 'geometry'] = result[1]
        edges_gdf.at[new_index, 'u'] = node
        edges_gdf.at[new_index, 'v'] = last_node
        edges_gdf.at[new_index, 'streetID'] = new_index
        gline = result[1]
        
        if (update_counts == True) & (counter == len(list_nodes)-1): 
            edges_gdf.at[new_index, 'counts'] = edges_gdf.loc[ix_line].counts + edges_gdf.loc[list_lines[counter+1]].counts
                                                                                                         

def interpolate_multi(first_node, last_node, center_line, list_nodes, list_lines, nodes_gdf, edges_gdf, ix_line, update_counts = False):
    gline = center_line  
    new_index = ix_line
                                                                                                         
    distances = {}
    lines_distances = {}
    
    for node in list_nodes:
        distance = nodes_gdf.loc[node]['geometry'].distance(Point(center_line.coords[0])) #rev!
        distances[node] = distance
                                                                                                         
    for line in list_lines:
        distance = edges_gdf.loc[line]['geometry'].distance(Point(center_line.coords[-1])) #rev!
        lines_distances[line] = distance                                                                                                   

    distances_sorted = sorted(distances.items(), key=lambda kv: kv[1])               
    lines_distances_sorted = sorted(lines_distances.items(), key=lambda kv: kv[1])
    if update_counts == True: previous_index = ix_line
                                                                                                         
    for counter, node in enumerate(distances_sorted):
        
        node = distances_sorted[counter][0]
        point = nodes_gdf.loc[node].geometry
        result, np = split_line_interpolation(point, gline)
        
        #first part of the segment, adjusting node coordinates
        nodes_gdf.at[node, 'x'] = np.coords[0][0]
        nodes_gdf.at[node, 'y'] = np.coords[0][1]
        nodes_gdf.at[node, 'geometry'] = np
        
        if counter == 0: edges_gdf.at[new_index, 'u'] = first_node
        edges_gdf.at[new_index, 'geometry'] = result[0]
        edges_gdf.at[new_index, 'v'] = node
        if update_counts == True: 
            count = edges_gdf.loc[lines_distances_sorted[counter][0]].counts
            edges_gdf.at[new_index, 'counts'] = count
            # update previous count, only from second segment on
            if previous_index != ix_line: edges_gdf.at[previous_index, 'counts'] = count + edges_gdf.loc[previous_index].counts
            previous_index = new_index                                                             
           
        # second part of the segment
        new_index = max(edges_gdf.index)+1
        
        edges_gdf.loc[new_index] = edges_gdf.loc[ix_line]
        edges_gdf.at[new_index, 'geometry'] = result[1]
        edges_gdf.at[new_index, 'u'] = node
        edges_gdf.at[new_index, 'v'] = last_node
        edges_gdf.at[new_index, 'streetID'] = new_index
        gline = result[1]                
        
        if (update_counts == True) & (counter == len(list_nodes)-1): 
            final_count = 0
            nL = len(list_nodes)-len(list_lines)+1                                                                                         
            for i in range(1, nL): final_count += edges_gdf.loc[lines_distances_sorted[counter+i][0]]
            edges_gdf.at[new_index, 'counts'] = final_count
            edges_gdf.at[previous_index, 'counts'] = final_count + edges_gdf.loc[previous_index].counts                           
                                                                         
def merge_two(ix_lineA, ix_lineB, glineA, glineB, nodes_gdf, edges_gdf, clusters_gdf, cluster, goal, direction, update_counts = False):
    
    # some pre criteria
    if (((glineA.centroid.distance(glineB.centroid) > 18) & 
       (edges_gdf.loc[ix_lineA]['name'] != edges_gdf.loc[ix_lineB]['name'])) | 
        ((glineA.length > glineB.length*1.50) | (glineB.length > glineA.length*1.50))):
        return None

    cl = center_line_cluster(glineA, glineB, nodes_gdf, clusters_gdf, cluster, goal)
    
    if direction == 'u':
        line_coords = list(cl.coords)
        line_coords.reverse() 
        cl = LineString([coor for coor in line_coords])
    
    edges_gdf.at[ix_lineA, 'geometry'] = cl
    if  update_counts == True: edges_gdf.at[ix_lineA, 'counts'] = edges_gdf.loc[ix_lineA].counts + edges_gdf.loc[ix_lineB].counts
    return 'processed'

    
def merge_two_inter(ix_lineA, ix_lineB, glineA, glineB, nodes_gdf, edges_gdf, clusters_gdf, cluster, goal, 
                               starting_node, last_node, list_nodes, list_lines, multi = False, update_counts = False):
    # the center line is built in relation to the variable cluster as 'u', or from_node --> to_node
    if (((glineA.centroid.distance(glineB.centroid) > 18) & 
       (edges_gdf.loc[ix_lineA]['name'] != edges_gdf.loc[ix_lineB]['name'])) | 
        ((glineA.length > glineB.length*1.50) | (glineB.length > glineA.length*1.50))):
        return None
    
    cl = center_line_cluster(glineA, glineB, nodes_gdf, clusters_gdf, cluster, goal)
    if multi == True: interpolate_multi(starting_node, last_node, cl, 
                                        list_nodes, list_lines, nodes_gdf, edges_gdf, ix_lineA, update_counts = update_counts)
    else: interpolate(starting_node, last_node, cl, list_nodes, list_lines, nodes_gdf, edges_gdf, ix_lineA, 
                      update_counts = update_counts) 
    return 'processed'

def find_central(dict_lines, nodes_gdf, clusters_gdf, cluster, goal):
    secondary_lines = []
    max_dist = 0
    
    if len(dict_lines)%2 != 0:                                                        
        for key, value in dict_lines.items():
            for keyC, valueC in dict_lines.items():
                if key == keyC: continue
                distance = (value.centroid).distance(valueC.centroid)
                if distance > max_dist: 
                    max_dist = distance
                    secondary_lines = [key, keyC]

        central = [x for x in list(dict_lines.keys()) if x not in secondary_lines][0]  
        geo_central = dict_lines[central]
    
    else:
        geo_central = center_line_cluster_four(list(dict_lines.values()), nodes_gdf, clusters_gdf, cluster, goal)                         
        central, secondary_lines = None, None
       
    return(central, secondary_lines, geo_central)
  

def simplify_dual_lines(nodes_gdf, edges_gdf, clusters_gdf, update_counts = False):
    nodes_gdf, edges_gdf = nodes_gdf.copy(), edges_gdf.copy()
    
    ix_geo = edges_gdf.columns.get_loc("geometry")+1
    ix_u, ix_v  = edges_gdf.columns.get_loc("u")+1, edges_gdf.columns.get_loc("v")+1
    ix_name = edges_gdf.columns.get_loc("name")+1
    ix_cluster = nodes_gdf.columns.get_loc("cluster")+1
    ix_clus_u, ix_clus_v  = edges_gdf.columns.get_loc("clus_u")+1, edges_gdf.columns.get_loc("clus_v")+1
    ix_clus_uR, ix_clus_vR = edges_gdf.columns.get_loc("clus_uR")+1, edges_gdf.columns.get_loc("clus_vR")+1
    
    ################################ FROM NODES TO CLUSTERED JUNCTIONS
    
    clusters_gdf['keep'] = False
    o_edges = edges_gdf.copy()  
    processed = []
    to_drop = []
    list_cluster = clusters_gdf.index.values.tolist() 
    
    print('Simplifying dual lines: First part - clusters')

    for cluster in list_cluster:
           
        edges_tmp = o_edges[((o_edges.clus_u == cluster) | (o_edges.clus_v == cluster))].copy()
        edges_tmp = edges_tmp[edges_tmp.clus_u != edges_tmp.clus_v].copy()
        
        if len(edges_tmp) == 1: continue
        for row in edges_tmp.itertuples():
            if row.Index in processed: continue  
            pDL = edges_tmp.copy() 
            
            # disregard unparallel lines 
            for rowC in pDL.itertuples():
                if row.Index == rowC.Index: continue
                elif rowC.Index in processed: pDL.drop(rowC.Index, axis = 0, inplace = True)
                elif ((row[ix_u] == rowC[ix_u]) | (row[ix_u] == rowC[ix_v]) |  (row[ix_v] == rowC[ix_v]) |
                (row[ix_v] == rowC[ix_u])): pDL.drop(rowC.Index, axis = 0, inplace = True)
                elif iscontinuation(row.Index, rowC.Index, o_edges) == True: continue
                else: 
                    pDL.drop(rowC.Index, axis = 0, inplace = True)            

            # does the line considered in the loop reach a cluster? if not straight away, at some point?
            pDL['dir'] = 'v'
            # orientate everything from "u" to "v"
            
            for rowC in pDL.itertuples():
                if rowC[ix_clus_v] == cluster:
                    line_coords = list(rowC[ix_geo].coords)
                    line_coords.reverse() 
                    new_gline = LineString([coor for coor in line_coords])
                    old_u = rowC[ix_u]
                    old_clus_u = rowC[ix_clus_u]
                    old_clus_uR = rowC[ix_clus_uR]

                    pDL.at[rowC.Index,'geometry'] = new_gline
                    pDL.at[rowC.Index,'u']  = rowC[ix_v]
                    pDL.at[rowC.Index,'v'] = old_u
                    pDL.at[rowC.Index,'clus_u'] = rowC[ix_clus_v]
                    pDL.at[rowC.Index,'clus_v'] = old_clus_u
                    pDL.at[rowC.Index,'clus_uR'] = rowC[ix_clus_vR]
                    pDL.at[rowC.Index,'clus_vR'] = old_clus_uR
                    pDL.at[rowC.Index, 'dir'] = 'u' # indicates original dir
     
            if pDL.loc[row.Index]['clus_v'] != None: pDL_goal = pDL.loc[row.Index]['clus_v']
            else: pDL_goal = pDL.loc[row.Index]['clus_vR']
            if (pDL_goal == None) | (pDL_goal == cluster): continue
            for rowC in pDL.itertuples():
                if rowC[ix_clus_v] != None: secondary_goal = rowC[ix_clus_v]
                else: secondary_goal = rowC[ix_clus_vR]
                if (secondary_goal != pDL_goal): pDL.drop(rowC.Index, axis = 0, inplace = True)
            
            done = False
            ######################################################## OPTION 1
            while(done == False):
                
                if len(pDL) == 1: break # no parallel streets to row.Index 
                if len(pDL) > 4: 
                    break
                    print("cannot handle this set")
                    
                ######################################################## OPTION 2

                elif len(pDL) == 2:

                    list_nodes = []
                    c_u, c_uC = pDL.iloc[0]['clus_u'], pDL.iloc[1]['clus_u']
                    c_v, c_vC, = pDL.iloc[0]['clus_v'], pDL.iloc[1]['clus_v']
                    u, uC =  pDL.iloc[0]['u'], pDL.iloc[1]['u']
                    v, vC = pDL.iloc[0]['v'], pDL.iloc[1]['v']
                    dr, drC = pDL.iloc[0]['dir'], pDL.iloc[1]['dir']
                    gline, glineC = pDL.iloc[0]['geometry'], pDL.iloc[1]['geometry']
                    ix_line, ix_lineC  = pDL.iloc[0].name, pDL.iloc[1].name
                    lines = [ix_line, ix_lineC]

                    ######################################################## 
                    ## SUB-OPTION 1: they all reach another cluster:

                    if (c_v == c_vC) & (c_v != None):
                        lines_traversed = []
                        goal = c_v
                        
                        if (gline.length > glineC.length*1.50) & (glineC.length > gline.length*1.50):
                            print(ix_line, ix_lineC, 'not COMPLETED: OPTION 2 - SECTION 2')
                            break
                        
                        p = merge_two(ix_line, ix_lineC, gline, glineC, nodes_gdf, edges_gdf, clusters_gdf, cluster,
                                      goal, dr, update_counts =  update_counts)
                        if p is None: 
                            print(ix_line, ix_lineC, 'not COMPLETED: OPTION 2 - SECTION 1')
                            break
                        print(ix_line, ix_lineC, 'OPTION 2 - SECTION 1')
                        to_drop = to_drop + [ix_lineC]

                    ######################################################## 
                    ## SUB-OPTION 2: only one reaches another cluster:

                    elif (c_v != None) | (c_vC != None):
                        if c_v != None: 
                            goal = c_v
                            found, glineC, lines_t, list_nodes, vC = next_cluster(nodes_gdf, o_edges, ix_lineC, drC)
                            lines_t.insert(0, ix_lineC)
                            last_node = vC                          
                        else: 
                            goal = c_vC
                            found, gline, lines_t, list_nodes, v = next_cluster(nodes_gdf, o_edges, ix_line, dr)
                            lines_t.insert(0, ix_line)
                            last_node = v
                        
                        if (gline.length > glineC.length*1.50) & (glineC.length > gline.length*1.50):
                            print(ix_line, ix_lineC, 'not COMPLETED: OPTION 2 - SECTION 2')
                            break
                            
                        lines_traversed = lines_t
                        
                        # update counts with in between segments' counts  
                        if update_counts == True:
                            bc = list(o_edges.index[((o_edges.clus_u == cluster) & (o_edges.v.isin(list_nodes))) | 
                                                    ((o_edges.clus_v == cluster) & (o_edges.u.isin(list_nodes))) |
                                                    ((o_edges.clus_uR == cluster) & (o_edges.u.isin(list_nodes)))|
                                                    ((o_edges.clus_vR == cluster) & (o_edges.u.isin(list_nodes)))])
                           
                            bg = list(o_edges.index[((o_edges.clus_u == goal) & (o_edges.v.isin(list_nodes))) | 
                                                    ((o_edges.clus_v == goal) & (o_edges.u.isin(list_nodes))) |
                                                    ((o_edges.clus_uR == goal) & (o_edges.u.isin(list_nodes)))|
                                                    ((o_edges.clus_vR == goal) & (o_edges.u.isin(list_nodes)))])
                            for lt in lines_traversed:
                                if lt in bc:
                                    for ltC in bc: 
                                        if lt == ltC: continue
                                        if ltC in lines: continue
                                        else: edges_gdf.at[lt, 'counts'] = edges_gdf.loc[lt].counts + edges_gdf.loc[ltC].counts

                                if lt in bg:
                                    for ltC in bg: 
                                        if lt == ltC: continue
                                        if ltC in lines: continue
                                        else: edges_gdf.at[lt, 'counts'] = edges_gdf.loc[lt].counts + edges_gdf.loc[ltC].counts
                        
                        p = merge_two_inter(ix_line, ix_lineC, gline, glineC, nodes_gdf, edges_gdf, clusters_gdf,
                                     cluster, goal, u, last_node, list_nodes, lines_traversed, update_counts =  update_counts)
                        if p is None: 
                            print(ix_line, ix_lineC, 'not COMPLETED: OPTION 2 - SECTION 2')
                            break
                            
                        print(ix_line, ix_lineC, 'OPTION 2 - SECTION 2')
                        to_drop = to_drop + lines_t + [ix_lineC, ix_line]
                        to_drop = list(filter(lambda a: a != ix_line, to_drop))

                    ####################################################### 
                    # SUB-OPTION 3: none reaches a cluster directly; comparing the first reached cluster
                    else: 
                        goal, gline, lines_t, nodes_en, v = next_cluster(nodes_gdf, o_edges, ix_line, dr)
                        destC, glineC, lines_tC, nodes_enC, vC = next_cluster(nodes_gdf, o_edges, ix_lineC, drC)  
                        common = list(set(lines_t).intersection(lines_tC))
                        if len(common) > 0: break
                        list_nodes = nodes_en + nodes_enC
                        if update_counts == True:
                            lines_t.insert(0, ix_line)
                            lines_tC.insert(0, ix_lineC)
                        
                        lines_traversed = lines_t + lines_tC
                        # update counts with in between segments' counts  
                        if update_counts == True:
                            bc = list(o_edges.index[((o_edges.clus_u == cluster) & (o_edges.v.isin(list_nodes))) | 
                                                    ((o_edges.clus_v == cluster) & (o_edges.u.isin(list_nodes))) |
                                                    ((o_edges.clus_uR == cluster) & (o_edges.u.isin(list_nodes)))|
                                                    ((o_edges.clus_vR == cluster) & (o_edges.u.isin(list_nodes)))])
                           
                            bg = list(o_edges.index[((o_edges.clus_u == goal) & (o_edges.v.isin(list_nodes))) | 
                                                    ((o_edges.clus_v == goal) & (o_edges.u.isin(list_nodes))) |
                                                    ((o_edges.clus_uR == goal) & (o_edges.u.isin(list_nodes)))|
                                                    ((o_edges.clus_vR == goal) & (o_edges.u.isin(list_nodes)))])
                            for lt in lines_traversed:
                                if lt in bc:
                                    for ltC in bc: 
                                        if lt == ltC: continue
                                        if ltC in lines: continue
                                        else: edges_gdf.at[lt, 'counts'] = edges_gdf.loc[lt].counts + edges_gdf.loc[ltC].counts

                                if lt in bg:
                                    for ltC in bg: 
                                        if lt == ltC: continue
                                        if ltC in lines: continue
                                        else: edges_gdf.at[lt, 'counts'] = edges_gdf.loc[lt].counts + edges_gdf.loc[ltC].counts             
                        # last node does not matter, as it will be reassigned to the relative cluster
                        p = merge_two_inter(ix_line, ix_lineC, gline, glineC, nodes_gdf, edges_gdf, clusters_gdf, 
                                          cluster, goal, u, v, list_nodes, lines_traversed, multi = True, update_counts =  update_counts)
                        if p is None: 
                            print(ix_line, ix_lineC, 'not COMPLETED: OPTION 2 - SECTION 3')
                            break
                            
                        to_drop = to_drop + lines_tC + lines_t
                        to_drop = list(filter(lambda a: a != ix_line, to_drop))
                        print(ix_line, ix_lineC, 'OPTION 2 - SECTION 3') 
                          
                    clusters = [cluster, goal]    
                    between = (
                            list(o_edges.index[(o_edges.u.isin(list_nodes)) & (o_edges.v.isin(list_nodes))])+
                            list(o_edges.index[(o_edges.clus_u.isin(clusters)) & (o_edges.v.isin(list_nodes))])+
                            list(o_edges.index[(o_edges.clus_v.isin(clusters)) & (o_edges.u.isin(list_nodes))])+ 
                            list(o_edges.index[(o_edges.clus_uR.isin(clusters)) & (o_edges.v.isin(list_nodes))])+
                            list(o_edges.index[(o_edges.clus_vR.isin(clusters)) & (o_edges.u.isin(list_nodes))]))
                    
                    between = list(set(between)-set(lines_traversed)-set(lines))     
                    to_drop = to_drop + between  
                    processed = processed + [ix_line] + to_drop
                    clusters_gdf.at[clusters, 'keep'] =  True
                    if len(o_edges.loc[processed][o_edges.pedestrian == 1]) > 0: edges_gdf.at[ix_line, 'pedestrian'] = 1
#                     edges_gdf.drop(to_drop, axis = 0, inplace = True, errors = 'ignore')
                    done = True

                ####################################################### OPTION 3

                elif len(pDL) == 3:
                    list_nodes = []
                    c_u, c_uC, c_uCC = pDL.iloc[0]['clus_u'], pDL.iloc[1]['clus_u'], pDL.iloc[2]['clus_u']
                    c_v, c_vC, c_vCC = pDL.iloc[0]['clus_v'], pDL.iloc[1]['clus_v'], pDL.iloc[2]['clus_v']
                    u, uC, uCC =  pDL.iloc[0]['u'], pDL.iloc[1]['u'], pDL.iloc[2]['u']
                    v, vC, vCC = pDL.iloc[0]['v'], pDL.iloc[1]['v'], pDL.iloc[2]['v']
                    if (uC == uCC) | (uC == vCC) | (vC == uCC) | (vC == vCC): break
                    dr, drC, drCC = pDL.iloc[0]['dir'], pDL.iloc[1]['dir'], pDL.iloc[2]['dir']
                    gline, glineC, glineCC = pDL.iloc[0]['geometry'], pDL.iloc[1]['geometry'], pDL.iloc[2]['geometry']
                    ix_line, ix_lineC, ix_lineCC  = pDL.iloc[0].name, pDL.iloc[1].name, pDL.iloc[2].name            
                    lines = [ix_line, ix_lineC, ix_lineCC]
                    ######################################################## 
                    ## SUB-OPTION 1: they all reach another cluster (the same)
                    
                    if ((c_v == c_vC) & (c_v == c_vCC) & (c_v != None)):
                        goal = c_v

                        # checking length
                        if (gline.length > glineC.length*1.50) & (gline.length > glineCC.length*1.50):
                            pDL.drop(ix_line, axis = 0, inplace = True)
                        elif (glineC.length > gline.length*1.50) & (glineC.length > glineCC.length*1.50):
                            pDL.drop(ix_lineC, axis = 0, inplace = True)
                        elif (glineCC.length > gline.length*1.50) & (glineCC.length > glineC.length*1.50):
                            pDL.drop(ix_lineC, axis = 0, inplace = True)
                        else:  
                            dict_lines = {ix_line: gline, ix_lineC: glineC, ix_lineCC: glineCC}
                            if  update_counts == True: 
                                indexes = [ix_line, ix_lineC, ix_lineCC]
                                count = edges_gdf[edges_gdf.index.isin(indexes)].counts.sum()
                            
                            print(ix_line, ix_lineC, ix_lineCC, 'OPTION 3 - SECTION 1')
                            ix_line, secondary = find_central(dict_lines, nodes_gdf, clusters_gdf, cluster, goal)[0:2]
                            to_drop = to_drop + secondary
                            if  update_counts == True: edges_gdf.at[ix_line, 'counts'] = count
                            done = True
                            # no need to change geometry here

                    ########################################################  
                    ## SUB-OPTION 2: two reach another cluster:   
                    
                    elif (((c_v == c_vC) & (c_v != None))| ((c_v == c_vCC) & (c_v != None)) | ((c_vC == c_vCC) & (c_vC != None))):

                        if (c_v == c_vC) & (c_v != None):
                            goal, glineCC, lines_t, list_nodes, last_node = next_cluster(nodes_gdf, o_edges, ix_lineCC, drCC)
                            ix = ix_line
                            if  update_counts == True: 
                                lines_t.insert(0, ix_lineCC)
                                main_count = o_edges.loc[ix_line].counts + o_edges.loc[ix_lineC].counts
                        elif (c_v == c_vCC) & (c_v != None):
                            goal, glineC, lines_t, list_nodes, last_node = next_cluster(nodes_gdf, o_edges, ix_lineC, drC)
                            ix = ix_line
                            if  update_counts == True: 
                                lines_t.insert(0, ix_lineC)
                                main_count = o_edges.loc[ix_line].counts + o_edges.loc[ix_lineCC].counts
                        elif (c_vC == c_vCC) & (c_vC != None):
                            goal, gline, lines_t, list_nodes, last_node = next_cluster(nodes_gdf, o_edges, ix_line, dr)
                            ix = ix_lineC
                            if  update_counts == True: 
                                main_count = o_edges.loc[ix_lineC].counts + o_edges.loc[ix_lineCC].counts
                                lines_t.insert(0, ix_line)
                          
                        if (gline.length > glineC.length*1.50) & (gline.length > glineCC.length*1.50):
                            pDL.drop(ix_line, axis = 0, inplace = True)
                        elif (glineC.length > gline.length*1.50) & (glineC.length > glineCC.length*1.50):
                            pDL.drop(ix_lineC, axis = 0, inplace = True)
                        elif (glineCC.length > gline.length*1.50) & (gline.length > glineC.length*1.50):
                            pDL.drop(ix_lineCC, axis = 0, inplace = True)
                        else:
                            dict_lines = {ix_line: gline, ix_lineC: glineC, ix_lineCC: glineCC}
                            ix_central, secondary_lines, cl = find_central(dict_lines, nodes_gdf, clusters_gdf, cluster, goal)
                            
                            to_drop = to_drop + secondary_lines + lines_t + [ix_central]
                            to_drop = list(filter(lambda a: a != ix, to_drop))
                            # to use inside the function
                            if  update_counts == True: edges_gdf.at[ix, 'counts'] = main_count
                            lines_traversed = lines_t
                            
                            # update counts with in between segments' counts  
                            if update_counts == True:
                                bc = list(o_edges.index[((o_edges.clus_u == cluster) & (o_edges.v.isin(list_nodes))) | 
                                                        ((o_edges.clus_v == cluster) & (o_edges.u.isin(list_nodes))) |
                                                        ((o_edges.clus_uR == cluster) & (o_edges.u.isin(list_nodes)))|
                                                        ((o_edges.clus_vR == cluster) & (o_edges.u.isin(list_nodes)))])

                                bg = list(o_edges.index[((o_edges.clus_u == goal) & (o_edges.v.isin(list_nodes))) | 
                                                        ((o_edges.clus_v == goal) & (o_edges.u.isin(list_nodes))) |
                                                        ((o_edges.clus_uR == goal) & (o_edges.u.isin(list_nodes)))|
                                                        ((o_edges.clus_vR == goal) & (o_edges.u.isin(list_nodes)))])
                                for lt in lines_traversed:
                                    if lt in bc:
                                        for ltC in bc: 
                                            if lt == ltC: continue
                                            if ltC in lines: continue
                                            else: edges_gdf.at[lt, 'counts'] = edges_gdf.loc[lt].counts + edges_gdf.loc[ltC].counts

                                    if lt in bg:
                                        for ltC in bg: 
                                            if lt == ltC: continue
                                            if ltC in lines: continue
                                            else: edges_gdf.at[lt, 'counts'] = edges_gdf.loc[lt].counts + edges_gdf.loc[ltC].counts        
                                          
                            interpolate(u, last_node, cl, list_nodes, lines_traversed, nodes_gdf, edges_gdf, ix,
                                        update_counts =  update_counts)
                            
                            done = True
                            print(ix_line, ix_lineC, ix_lineCC, 'OPTION 3 - SECTION 2')
                            ix_line = ix
                            
                    ########################################################  
                    ## SUB-OPTION 3: only one reaches a cluster:

                    elif (c_v != None)| (c_vC != None) | (c_vCC != None):

                        only_two = False # a line connects from the existing main lines to the cluster

                        if (c_v != None):
                            if (uC == u) | (uCC == u): only_two = True
                            else:
                                if  update_counts == True: main_count = o_edges.loc[ix_line].counts
                                destC, glineC, lines_tC, nodes_enC, last_node = next_cluster(nodes_gdf, o_edges, ix_lineC, drC)
                                destCC, glineCC, lines_tCC, nodes_enCC, last_nodeCC = next_cluster(nodes_gdf, o_edges, ix_lineCC, drCC)
                                lines_t, nodes_en = [], []
                                goal = c_v
                        elif (c_vC != None):
                            if (u == uC) | (uCC == uC): only_two = True
                            else:
                                if  update_counts == True: main_count = o_edges.loc[ix_lineC].counts
                                dest, gline, lines_t, nodes_en, last_node = next_cluster(nodes_gdf, o_edges, ix_line, dr)
                                destCC, glineCC, lines_tCC, nodes_enCC, last_nodeCC = next_cluster(nodes_gdf, o_edges, ix_lineCC, drCC)
                                lines_tC, nodes_enC = [], []
                                goal = c_vC
                        else:
                            if (u == uCC) | (uC == uCC): only_two = True
                            else:
                                if  update_counts == True: main_count = o_edges.loc[ix_lineCC].counts
                                dest, gline, lines_t, nodes_en, last_node = next_cluster(nodes_gdf, o_edges, ix_line, dr)
                                destC, glineC, lines_tC, nodes_enC, last_nodeC = next_cluster(nodes_gdf, o_edges, ix_lineC, drC) 
                                lines_tCC, nodes_enCC = [], []
                                goal = c_vCC

                        if only_two == True:          
                            
                            if c_v != None:
                                goal = c_v
                                if uC == u:
                                    found, glineC, lines_t, list_nodes, last_node = next_cluster(nodes_gdf, o_edges, ix_lineCC, drCC)
                                    if  update_counts == True: 
                                        lines_t.insert(0, ix_lineCC)
                                        to_add = o_edges.loc[ix_lineC].counts
                                else: #uCC = u 
                                    found, glineC, lines_t, list_nodes, last_node = next_cluster(nodes_gdf, o_edges, ix_lineC, drC)
                                    if  update_counts == True: 
                                        lines_t.insert(0, ix_lineC)
                                        to_add = o_edges.loc[ix_lineCC].counts
                                
                                if (gline.length > glineC.length*1.50) | (glineC.length > gline.length*1.50): break
                                cl = center_line_cluster(gline, glineC, nodes_gdf, clusters_gdf, cluster, goal)
                                to_drop = to_drop + lines_t +[ix_lineC, ix_lineCC]

                            elif c_vC != None:
                                goal = c_vC
                                if u == uC: # use CC
                                    found, gline,lines_t,list_nodes,last_node=next_cluster(nodes_gdf, o_edges,ix_lineCC,drCC)
                                    if  update_counts == True: 
                                        lines_t.insert(0, ix_lineCC)
                                        to_add = o_edges.loc[ix_line].counts
                                else: #uCC = uC # use --
                                    found, gline,lines_t,list_nodes,last_node = next_cluster(nodes_gdf, o_edges,ix_line,dr)
                                    if  update_counts == True: 
                                        lines_t.insert(0, ix_line)
                                        to_add = o_edges.loc[ix_lineCC].counts
                          
                                if (gline.length > glineC.length*1.50) | (glineC.length > gline.length*1.50): break
                                cl = center_line_cluster(glineC, glineC, nodes_gdf, clusters_gdf, cluster, goal)
                                ix_line = ix_lineC
                                to_drop = to_drop + lines_t +[ix_line, ix_lineCC]

                            elif c_vCC != None:
                                goal = c_vCC
                                if u == uCC: #use C
                                    found, glineC, lines_t, list_nodes, last_node = next_cluster(nodes_gdf, o_edges,ix_lineC,drC)
                                    last_node = v
                                    if  update_counts == True: 
                                        lines_t.insert(0, ix_lineC)
                                        to_add = o_edges.loc[ix_line].counts
                                else: # uC = uCC #use --
                                    found, glineC, lines_t, list_nodes, last_node = next_cluster(nodes_gdf, o_edges,ix_line,dr)
                                    last_node = vC  
                                    if  update_counts == True: 
                                        lines_t.insert(0, ix_line)
                                        to_add = o_edges.loc[ix_lineC].counts
                                
                                if (gline.length > glineC.length*1.50) | (glineC.length > gline.length*1.50): break
                                cl = center_line_cluster(glineCC, glineC, nodes_gdf, clusters_gdf, cluster, goal)
                                ix_line = ix_lineCC
                                to_drop = to_drop + lines_t +[ix_line, ix_lineC]
                            
                            to_drop = list(filter(lambda a: a != ix_line, to_drop))
                            edges_gdf.at[ix_line, 'counts'] = edges_gdf.loc[ix_line].counts + to_add
                            lines_traversed = lines_t
                            
                            # update counts with in between segments' counts  
                            if update_counts == True:
                                bc = list(o_edges.index[((o_edges.clus_u == cluster) & (o_edges.v.isin(list_nodes))) | 
                                                        ((o_edges.clus_v == cluster) & (o_edges.u.isin(list_nodes))) |
                                                        ((o_edges.clus_uR == cluster) & (o_edges.u.isin(list_nodes)))|
                                                        ((o_edges.clus_vR == cluster) & (o_edges.u.isin(list_nodes)))])

                                bg = list(o_edges.index[((o_edges.clus_u == goal) & (o_edges.v.isin(list_nodes))) | 
                                                        ((o_edges.clus_v == goal) & (o_edges.u.isin(list_nodes))) |
                                                        ((o_edges.clus_uR == goal) & (o_edges.u.isin(list_nodes)))|
                                                        ((o_edges.clus_vR == goal) & (o_edges.u.isin(list_nodes)))])
                                for lt in lines_traversed:
                                    if lt in bc:
                                        for ltC in bc: 
                                            if lt == ltC: continue
                                            if ltC in lines: continue
                                            else: edges_gdf.at[lt, 'counts'] = edges_gdf.loc[lt].counts + edges_gdf.loc[ltC].counts

                                    if lt in bg:
                                        for ltC in bg: 
                                            if lt == ltC: continue
                                            if ltC in lines: continue
                                            else: edges_gdf.at[lt, 'counts'] = edges_gdf.loc[lt].counts + edges_gdf.loc[ltC].counts
                                          
                            interpolate(u, last_node, cl, list_nodes, lines_traversed, nodes_gdf, edges_gdf, ix_line, 
                                        update_counts =  update_counts)              
                            processed = processed + [ix_line] + to_drop
                            done = True
                            print(ix_line, ix_lineC, ix_lineCC, 'OPTION 3 - SECTION 3 - SUBSECTION2')
                        
                        else:
                            if (gline.length > glineC.length*1.50) & (gline.length > glineCC.length*1.50):
                                pDL.drop(ix_line, axis = 0, inplace = True)
                            elif (glineC.length > gline.length*1.50) & (glineC.length > glineCC.length*1.50):
                                pDL.drop(ix_lineC, axis = 0, inplace = True)
                            elif (glineCC.length > gline.length*1.50) & (glineCC.length > glineC.length*1.50):
                                pDL.drop(ix_lineCC, axis = 0, inplace = True)
                            else:
                                # exclude the 2 lines furter away                          
                                list_nodes = nodes_en + nodes_enC + nodes_enCC
                                dict_lines = {ix_line: gline, ix_lineC: glineC, ix_lineCC: glineCC}
                                
                                print(ix_line, ix_lineC, ix_lineCC, 'OPTION 3 - SECTION 3')
                                ix_central, secondary_lines, cl = find_central(dict_lines, nodes_gdf, clusters_gdf, cluster, goal)
                                ix_line = ix_central
                                to_drop = to_drop + secondary_lines + lines_t + lines_tC + lines_tCC
                                lines_traversed = lines_t + lines_tC + lines_tCC
                                
                                # update counts with in between segments' counts  
                                if update_counts == True:
                                    bc = list(o_edges.index[((o_edges.clus_u == cluster) & (o_edges.v.isin(list_nodes))) | 
                                                            ((o_edges.clus_v == cluster) & (o_edges.u.isin(list_nodes))) |
                                                            ((o_edges.clus_uR == cluster) & (o_edges.u.isin(list_nodes)))|
                                                            ((o_edges.clus_vR == cluster) & (o_edges.u.isin(list_nodes)))])

                                    bg = list(o_edges.index[((o_edges.clus_u == goal) & (o_edges.v.isin(list_nodes))) | 
                                                            ((o_edges.clus_v == goal) & (o_edges.u.isin(list_nodes))) |
                                                            ((o_edges.clus_uR == goal) & (o_edges.u.isin(list_nodes)))|
                                                            ((o_edges.clus_vR == goal) & (o_edges.u.isin(list_nodes)))])
                                    for lt in lines_traversed:
                                        if lt in bc:
                                            for ltC in bc: 
                                                if lt == ltC: continue
                                                if ltC in lines: continue
                                                else: edges_gdf.at[lt, 'counts'] = edges_gdf.loc[lt].counts + edges_gdf.loc[ltC].counts

                                        if lt in bg:
                                            for ltC in bg: 
                                                if lt == ltC: continue
                                                if ltC in lines: continue
                                                else: edges_gdf.at[lt, 'counts'] = edges_gdf.loc[lt].counts + edges_gdf.loc[ltC].counts         
                                to_drop = list(filter(lambda a: a != ix_line, to_drop))
                                if  update_counts == True: 
                                    for i in lines_traversed: edges_gdf.at[i, 'counts'] = main_count + edges_gdf.loc[i].counts 
                                interpolate_multi(u, last_node, cl, list_nodes, lines_traversed, nodes_gdf, edges_gdf, 
                                                  ix_line, update_counts =  update_counts)
                                done = True
                                
                                
                    ########################################################  
                    ## SUB-OPTION 4: none reaches a cluster:
                    else: 
                        goal, gline, lines_t, nodes_en, last_node = next_cluster(nodes_gdf, o_edges, ix_line, dr)
                        destC, glineC, lines_tC, nodes_enC, last_nodeC = next_cluster(nodes_gdf, o_edges, ix_lineC, drC)
                        destCC, glineCC, lines_tCC, nodes_enCC, last_nodeCC = next_cluster(nodes_gdf, o_edges, ix_lineCC, drCC)
                        
                        if (gline.length > glineC.length*1.50) & (gline.length > glineCC.length*1.50):
                            pDL.drop(ix_line, axis = 0, inplace = True)
                        elif (glineC.length > gline.length*1.50) & (glineC.length > glineCC.length*1.50):
                            pDL.drop(ix_lineC, axis = 0, inplace = True)
                        elif (glineCC.length > gline.length*1.50) & (glineCC.length > glineC.length*1.50):
                            pDL.drop(ix_lineCC, axis = 0, inplace = True)
                        
                        else:
                            # exclude the 2 lines furter away  
                            list_nodes = nodes_en + nodes_enC + nodes_enCC   
                            print(ix_line, ix_lineC, ix_lineCC, 'OPTION 3 - SECTION 4')
                            dict_lines = {ix_line: gline, ix_lineC: glineC, ix_lineCC: glineCC}
                            ix_central, secondary_lines, cl = find_central(dict_lines, nodes_gdf, clusters_gdf, cluster, goal)
                            ix_line = ix_central
                            to_drop = to_drop + secondary_lines + lines_t + lines_tC + lines_tCC
                            lines_traversed = lines_t + lines_tC + lines_tCC
                                          
                            # update counts with in between segments' counts  
                            if update_counts == True:
                                bc = list(o_edges.index[((o_edges.clus_u == cluster) & (o_edges.v.isin(list_nodes))) | 
                                                        ((o_edges.clus_v == cluster) & (o_edges.u.isin(list_nodes))) |
                                                        ((o_edges.clus_uR == cluster) & (o_edges.u.isin(list_nodes)))|
                                                        ((o_edges.clus_vR == cluster) & (o_edges.u.isin(list_nodes)))])

                                bg = list(o_edges.index[((o_edges.clus_u == goal) & (o_edges.v.isin(list_nodes))) | 
                                                        ((o_edges.clus_v == goal) & (o_edges.u.isin(list_nodes))) |
                                                        ((o_edges.clus_uR == goal) & (o_edges.u.isin(list_nodes)))|
                                                        ((o_edges.clus_vR == goal) & (o_edges.u.isin(list_nodes)))])
                                for lt in lines_traversed:
                                    if lt in bc:
                                        for ltC in bc: 
                                            if lt == ltC: continue
                                            if ltC in lines: continue
                                            else: edges_gdf.at[lt, 'counts'] = edges_gdf.loc[lt].counts + edges_gdf.loc[ltC].counts

                                    if lt in bg:
                                        for ltC in bg: 
                                            if lt == ltC: continue
                                            if ltC in lines: continue
                                            else: edges_gdf.at[lt, 'counts'] = edges_gdf.loc[lt].counts + edges_gdf.loc[ltC].counts                   
                            to_drop = list(filter(lambda a: a != ix_line, to_drop))  
                            interpolate_multi(u, last_node, cl, list_nodes, lines_traversed, nodes_gdf, edges_gdf, ix_line, 
                                              update_counts =  update_counts)    
                            done = True
                    
                    if done == False: pass
                    else:
                        clusters = [cluster, goal]
                        between = (
                        list(o_edges.index[(o_edges.u.isin(list_nodes)) & (o_edges.v.isin(list_nodes))])+
                        list(o_edges.index[(o_edges.clus_u.isin(clusters)) & (o_edges.v.isin(list_nodes))])+
                        list(o_edges.index[(o_edges.clus_v.isin(clusters)) & (o_edges.u.isin(list_nodes))])+ 
                        list(o_edges.index[(o_edges.clus_uR.isin(clusters))& (o_edges.v.isin(list_nodes))])+
                        list(o_edges.index[(o_edges.clus_vR.isin(clusters)) & (o_edges.u.isin(list_nodes))]))
                        
                        between = list(set(between)-set(lines_traversed)-set(lines))     
                        to_drop = to_drop + between
                        to_drop = list(filter(lambda a: a != ix_line, to_drop))
                        
                        processed = processed + [ix_line] + to_drop
                        clusters_gdf.at[clusters, 'keep'] = True
                        if len(o_edges.loc[processed][o_edges.pedestrian == 1]) > 0:
                            edges_gdf.at[ix_line, 'pedestrian'] = 1
#                         edges_gdf.drop(to_drop, axis = 0, inplace = True, errors = 'ignore')
                
                ######################################################## OPTION 1
                elif len(pDL) >3:
                    
#                     c_u = [pDL.iloc[i]['clus_u'] for i in range(0, len(pDL)+1)]
#                     c_v = [pDL.iloc[i]['clus_v'] for i in range(0, len(pDL)+1)]
#                     u =  [pDL.iloc[i]['u'] for i in range(0, len(pDL)+1)]   
#                     v =  [pDL.iloc[i]['v'] for i in range(0, len(pDL)+1)] 
#                     dr = [pDL.iloc[i]['dr'] for i in range(0, len(pDL)+1)] 
#                     gline = [pDL.iloc[i]['geometry'] for i in range(0, len(pDL)+1)]       
#                     ix_lines = [pDL.iloc[i].name for i in range(0, len(pDL)+1)]      
#                     nodes_en = [[] for i in range(0, len(pDL)+1)]
#                     lines_t = [[] for i in range(0, len(pDL)+1)]    
                    c_u,c_uC,c_uCC,c_uCCC = pDL.iloc[0]['clus_u'],pDL.iloc[1]['clus_u'],pDL.iloc[2]['clus_u'],pDL.iloc[3]['clus_u']
                    c_v,c_vC,c_vCC,c_vCCC = pDL.iloc[0]['clus_v'],pDL.iloc[1]['clus_v'],pDL.iloc[2]['clus_v'], pDL.iloc[3]['clus_v']
                    u, uC,uCC, uCCC =  pDL.iloc[0]['u'], pDL.iloc[1]['u'], pDL.iloc[2]['u'],pDL.iloc[3]['u']
                    v, vC, vCC, vCCC = pDL.iloc[0]['v'], pDL.iloc[1]['v'], pDL.iloc[2]['v'],pDL.iloc[3]['v']
                    dr, drC, drCC, drCCC = pDL.iloc[0]['dir'],pDL.iloc[1]['dir'],pDL.iloc[2]['dir'],pDL.iloc[3]['dir']
                    gline,glineC,glineCC, glineCCC=pDL.iloc[0]['geometry'],pDL.iloc[1]['geometry'],pDL.iloc[2]['geometry'],pDL.iloc[3]['geometry']
                    ix_line, ix_lineC, ix_lineCC, ix_lineCCC=pDL.iloc[0].name, pDL.iloc[1].name,pDL.iloc[2].name, pDL.iloc[3].name
                    nodes_en, nodes_enC, nodes_enCC, nodes_enCCC = [],[],[],[]
                    lines_t, lines_tC,lines_tCC, lines_tCCC = [],[],[],[]
                    last_node, goal = None, None
                    
                    if c_v == None:
                        goal, gline, lines_t, nodes_en, last_node = next_cluster(nodes_gdf, o_edges, ix_line, dr)
                        lines_t.insert(0, ix_line)
                    if c_vC == None:
                        goal, glineC, lines_tC, nodes_enC, last_node = next_cluster(nodes_gdf, o_edges, ix_lineC, drC)
                        lines_t.insert(0, ix_lineC)
                    if c_vCC == None:
                        goal, glineCC, lines_tCC, nodes_enCC, last_node = next_cluster(nodes_gdf, o_edges, ix_lineCC, drCC)
                        lines_tC.insert(0, ix_lineCC)
                    if (c_vCCC == None):
                        goal, glineCCC, lines_tCCC, nodes_enCCC, last_node = next_cluster(nodes_gdf, o_edges, ix_lineCCC, drCCC)  
                        lines_tCC.insert(0, ix_lineCCC)
                   
                    for i in [c_v, c_vC,c_vCC,c_vCCC]: 
                        goal = i
                        if goal != None: break
                        
                        
                    if last_node == None: last_node = v
                    dict_lines = {ix_line: gline, ix_lineC: glineC, ix_lineCC: glineCC, ix_lineCCC: glineCCC}
                    cl = find_central(dict_lines, nodes_gdf, clusters_gdf, cluster, goal)[2]

                    list_nodes = nodes_en + nodes_enC + nodes_enCC+nodes_enCCC 
                    lines_traversed = lines_t + lines_tC + lines_tCC + lines_tCCC

                    to_drop = to_drop + lines_traversed +[ix_lineC, ix_lineCC, ix_lineCCC]
                    to_drop = list(filter(lambda a: a != ix_line, to_drop))
                    
                    if  update_counts == True:
                        main_count = 0
                        if c_v != None: main_count += o_edges.loc[ix_line].counts
                        if c_vC != None: main_count += o_edges.loc[ix_lineC].counts
                        if c_vCC != None: main_count += o_edges.loc[ix_lineCC].counts
                        if c_vCCC != None: main_count += o_edges.loc[ix_lineCCC].counts
                        for lt in lines_traversed: edges_gdf.at[lt, 'counts'] = edges_gdf.loc[lt].counts + main_count
                        
                        # update counts with in between segments' counts                   
                        bc = list(o_edges.index[((o_edges.clus_u == cluster) & (o_edges.v.isin(list_nodes))) | 
                                                ((o_edges.clus_v == cluster) & (o_edges.u.isin(list_nodes))) |
                                                ((o_edges.clus_uR == cluster) & (o_edges.u.isin(list_nodes)))|
                                                ((o_edges.clus_vR == cluster) & (o_edges.u.isin(list_nodes)))])

                        bg = list(o_edges.index[((o_edges.clus_u == goal) & (o_edges.v.isin(list_nodes))) | 
                                                ((o_edges.clus_v == goal) & (o_edges.u.isin(list_nodes))) |
                                                ((o_edges.clus_uR == goal) & (o_edges.u.isin(list_nodes)))|
                                                ((o_edges.clus_vR == goal) & (o_edges.u.isin(list_nodes)))])
                        for lt in lines_traversed:
                            if lt in bc:
                                for ltC in bc: 
                                    if lt == ltC: continue
                                    if ltC in lines: continue
                                    else: edges_gdf.at[lt, 'counts'] = edges_gdf.loc[lt].counts + edges_gdf.loc[ltC].counts

                            if lt in bg:
                                for ltC in bg: 
                                    if lt == ltC: continue
                                    if ltC in lines: continue
                                    else: edges_gdf.at[lt, 'counts'] = edges_gdf.loc[lt].counts + edges_gdf.loc[ltC].counts
                    
                    
                    print(ix_line, ix_lineC, ix_lineCC, ix_lineCCC, 'OPTION 4')     
                    if len(list_nodes) == 0: 
                        edges_gdf.at[ix_line, 'counts']  = main_count
                        edges_gdf.at[ix_line, 'geometry']  = cl
                    else:
                        interpolate_multi(u, last_node, cl, list_nodes, lines_traversed, nodes_gdf, edges_gdf, ix_line, 
                                          update_counts =  update_counts)    
                    done = True
                    
                    clusters = [cluster, goal]
                    between = (
                    list(o_edges.index[(o_edges.u.isin(list_nodes))&(o_edges.v.isin(list_nodes))])+
                    list(o_edges.index[(o_edges.clus_u.isin(clusters))&(o_edges.v.isin(list_nodes))])+
                    list(o_edges.index[(o_edges.clus_v.isin(clusters))&(o_edges.u.isin(list_nodes))])+ 
                    list(o_edges.index[(o_edges.clus_uR.isin(clusters))&(o_edges.v.isin(list_nodes))])+
                    list(o_edges.index[(o_edges.clus_vR.isin(clusters))&(o_edges.u.isin(list_nodes))]))
                    
                    between = list(set(between)-set(lines_traversed)-set(lines))                                 
                    to_drop = to_drop + between
                    processed = processed + [ix_line] + to_drop
                    clusters_gdf.at[clusters, 'keep'] = True

                    if len(o_edges.loc[processed][o_edges.pedestrian == 1]) > 0:
                        edges_gdf.at[ix_line, 'pedestrian'] = 1
    
    edges_gdf.drop(to_drop, axis = 0, inplace = True, errors = 'ignore')
    edges_gdf['streetID'] = edges_gdf.index.values.astype(int)
    nodes_gdf['nodeID'] = nodes_gdf.index.values.astype(int)
    nodes_gdf, edges_gdf = reassign_edges(nodes_gdf, edges_gdf, clusters_gdf, update_counts = update_counts)   
    return(nodes_gdf, edges_gdf, clusters_gdf)    


def simplify_dual_linesNodes(nodes_gdf, edges_gdf, clusters_gdf,  update_counts = False):
    nodes_gdf, edges_gdf = nodes_gdf.copy(), edges_gdf.copy()
    processed = []
    print('Simplifying dual lines: Second part - nodes')
    edges_gdf = assign_cluster_edges(nodes_gdf, edges_gdf)

    o_edges = edges_gdf.copy()
    ix_geo = edges_gdf.columns.get_loc("geometry")+1
    ix_u, ix_v  = edges_gdf.columns.get_loc("u")+1, edges_gdf.columns.get_loc("v")+1
    ix_name = edges_gdf.columns.get_loc("name")+1
    ix_cluster = nodes_gdf.columns.get_loc("cluster")+1
    ix_clus_u, ix_clus_v  = edges_gdf.columns.get_loc("clus_u")+1, edges_gdf.columns.get_loc("clus_v")+1
    ix_clus_uR, ix_clus_vR = edges_gdf.columns.get_loc("clus_uR")+1, edges_gdf.columns.get_loc("clus_vR")+1
    clusters_gdf['keep'] = False
    to_drop = []
    
    for n in nodes_gdf.itertuples():
        tmp = o_edges[((o_edges.u == n[0]) | (o_edges.v == n[0]))].copy()
        for row in tmp.itertuples():
            if row.Index in processed: continue 
            if row[ix_u] == n[0]:
                goal = row[ix_clus_v]
                if goal is None: goal = row[ix_clus_vR]
            elif row[ix_v] == n[0]:
                goal = row[ix_clus_u]
                if goal is None: goal = row[ix_clus_uR]
            if goal is None: continue
                
            pDL = tmp[(tmp.clus_u == goal) | (tmp.clus_uR == goal) 
                         | (tmp.clus_v == goal) | (tmp.clus_vR == goal)].copy()
                
            # orientate everything from "u" to "v"
            pDL['dir'] = 'v'
            for g in pDL.itertuples():
                if g[ix_v] == n[0]:
                    line_coords = list(g[ix_geo].coords)
                    line_coords.reverse() 
                    new_gline = LineString([coor for coor in line_coords])
                    old_u, old_clus_u, old_clus_uR = g[ix_u], g[ix_clus_u], g[ix_clus_uR]
                    pDL.at[g[0],'geometry'] = new_gline
                    pDL.at[g[0],'u'] = g[ix_v]
                    pDL.at[g[0],'v'] = old_u
                    pDL.at[g[0],'clus_u'] = g[ix_clus_v]
                    pDL.at[g[0],'clus_v'] = old_clus_u
                    pDL.at[g[0],'clus_uR'] = g[ix_clus_vR]
                    pDL.at[g[0],'clus_vR'] = old_clus_uR
                    pDL.at[g[0], 'dir'] = 'u' # indicates original dir
                
            pDL = pDL[(pDL.clus_v == goal) | (pDL.clus_vR == goal)].copy()
            pDL = pDL[~pDL.index.isin(processed)]

            ######################################################## OPTION 1
            
            if len(pDL) == 1: continue # no parallel streets to row.Index 
                            
                ######################################################## OPTION 2
            list_nodes = []
                
            if len(pDL) == 2:                   
                c_v, c_vC, = pDL.iloc[0]['clus_v'], pDL.iloc[1]['clus_v']
                u, uC =  pDL.iloc[0]['u'], pDL.iloc[1]['u']
                v, vC = pDL.iloc[0]['v'], pDL.iloc[1]['v']
                gline, glineC = pDL.iloc[0]['geometry'], pDL.iloc[1]['geometry']
                dr, drC = pDL.iloc[0]['dir'], pDL.iloc[1]['dir']
                ix_line, ix_lineC  = pDL.iloc[0].name, pDL.iloc[1].name
                name, nameC = pDL.iloc[0]['name'], pDL.iloc[1]['name']
                if iscontinuation(ix_line, ix_lineC, o_edges) == True: pass
                else: continue

                ######################################################## 
                ## SUB-OPTION 1: they all reach another cluster:
                    
                if (c_v == c_vC) & (c_v != None):
                        
                    goal = c_v
                    if (gline.length > glineC.length *1.50) | (glineC.length > gline.length *1.50): continue
                    print(ix_line, ix_lineC, 'sub1 NODE', 'node ', n[0], 'cluster ', goal)
                    cl = uf.center_line(gline, glineC)
                    if dr == 'u':
                        line_coords = list(cl.coords)
                        line_coords.reverse() 
                        cl = LineString([coor for coor in line_coords])
                    
                    if  update_counts == True: 
                        edges_gdf.at[ix_line, 'counts'] = edges_gdf.loc[ix_line].counts + edges_gdf.loc[ix_lineC].counts
                    edges_gdf.at[ix_line, 'geometry'] = cl
                    to_drop = to_drop + [ix_lineC]

                ######################################################## 
                ## SUB-OPTION 2: only one reaches another cluster:

                elif (c_v != None) | (c_vC != None):
                    if c_v != None: 
                        goal = c_v
                        found, glineC, lines_t, list_nodes, vC = next_cluster(nodes_gdf, o_edges, ix_lineC, drC)
                        lines_t.insert(0, ix_lineC)
                        ix = ix_line
                        last_node = vC
                    else: 
                        goal = c_vC
                        found, gline, lines_t, list_nodes, v = next_cluster(nodes_gdf, o_edges, ix_line, dr)
                        lines_t.insert(0, ix_line)
                        ix = ix_lineC
                        last_node = v

                    if (gline.length > glineC.length *1.50) | (glineC.length > gline.length *1.50): continue  
                    print(ix_line, ix_lineC, 'sub2 NODE', 'node ', n[0], 'cluster ', goal)    
                    cl = center_line_cluster(gline, glineC, nodes_gdf, clusters_gdf, u, goal, one_cluster = True)
                    interpolate(u, last_node, cl, list_nodes, lines_t, nodes_gdf, edges_gdf, ix, update_counts = True)                   
                    to_drop = to_drop + lines_t + [ix_lineC] + [ix_line]
                    to_drop = list(filter(lambda a: a != ix, to_drop))
                    ix_line = ix

                ####################################################### 
                # SUB-OPTION 3: none reaches a cluster directly; comparing the first reached cluster
                else:  
                    print(ix_line, ix_lineC, 'sub3 NODE', 'node ', n[0], 'cluster ', goal)    
                    goal, gline, lines_t, nodes_en, v = next_cluster(nodes_gdf, o_edges, ix_line, dr)
                    destC, glineC, lines_tC, nodes_enC, vC = next_cluster(nodes_gdf, o_edges, ix_lineC, drC)    
                    if (gline.length > glineC.length *1.50) | (glineC.length > gline.length *1.50): continue
                                        
                    lines_t.insert(0, ix_line)
                    lines_t.insert(0, ix_lineC)
                    # the center line is built in relation to the variable cluster as 'u', or from_node --> to_node
                    cl =  center_line_cluster(gline, glineC, nodes_gdf, clusters_gdf, u, goal, one_cluster = True)
                    # last node does not matter, as it will be reassigned to the relative cluster
                    list_nodes = nodes_en + nodes_enC
                    lines_traversed = lines_t + lines_tC
                    interpolate_multi(u, v, cl, list_nodes, lines_traversed, nodes_gdf, edges_gdf, ix_line, update_counts = True)  
                    to_drop = to_drop+ lines_t + lines_tC + [ix_lineC]
                    to_drop = list(filter(lambda a: a != ix_line, to_drop))

                processed = processed + [ix_line] + to_drop
                
                if len(o_edges.loc[processed][o_edges.pedestrian == 1]) > 0: edges_gdf.at[ix_line, 'pedestrian'] = 1
#                 edges_gdf.drop(to_drop, axis = 0, inplace = True, errors = 'ignore')
                clusters_gdf.at[goal, 'keep'] = True
                continue
    
    edges_gdf.drop(to_drop, axis = 0, inplace = True, errors = 'ignore')
    nodes_gdf, edges_gdf = reassign_edges(nodes_gdf, edges_gdf, clusters_gdf, update_counts = update_counts)                
    edges_gdf['streetID'] = edges_gdf.index.values.astype(int)
    nodes_gdf['nodeID'] = nodes_gdf.index.values.astype(int)
    nodes_gdf.drop(['cluster'], axis = 1, inplace = True)
    return(nodes_gdf, edges_gdf)

def reassign_edges(nodes_gdf, edges_gdf, clusters_gdf, update_counts = False):
    
    print("Assigning centroids coordinates")
    nodes_gdf, edges_gdf = nodes_gdf.copy(), edges_gdf.copy()
    edges_gdf = edges_gdf.rename(columns = {'u':'old_u'})
    edges_gdf = edges_gdf.rename(columns = {'v':'old_v'})
    
    edges_gdf['u'] = 0
    edges_gdf['v'] = 0
    ix_u = edges_gdf.columns.get_loc("u")+1
    ix_v = edges_gdf.columns.get_loc("v")+1 
    ix_old_u = edges_gdf.columns.get_loc("old_u")+1
    ix_old_v = edges_gdf.columns.get_loc("old_v")+1
    ix_geo = edges_gdf.columns.get_loc("geometry")+1 
    
    ix_cluster = nodes_gdf.columns.get_loc("cluster")+1 
    ix_x = clusters_gdf.columns.get_loc("x")+1
    ix_y = clusters_gdf.columns.get_loc("y")+1
    ix_centroid = clusters_gdf.columns.get_loc("geometry")+1
    ix_check = clusters_gdf.columns.get_loc("keep")+1
    
    for row in edges_gdf.itertuples():
            
        line_coords = list(row[ix_geo].coords)
        u = nodes_gdf.loc[row[ix_old_u]]["cluster"]
        v = nodes_gdf.loc[row[ix_old_v]]["cluster"]
        old_u = row[ix_old_u]
        old_v = row[ix_old_v]
        if ((u != None) & (v != None)):  # change starting and ending node in the list of coordinates for the line
                if (clusters_gdf.loc[u].keep == False) & (clusters_gdf.loc[v].keep == False): 
                    u = old_u
                    v = old_v
                elif clusters_gdf.loc[v].keep == False:
                    v = old_v
                    line_coords[0] = (clusters_gdf.loc[u]['x'], clusters_gdf.loc[u]['y'])
                elif clusters_gdf.loc[u].keep == False: 
                    u = old_u    
                    line_coords[-1] = (clusters_gdf.loc[v]['x'], clusters_gdf.loc[v]['y'])
                else:
                    line_coords[0] = (clusters_gdf.loc[u]['x'], clusters_gdf.loc[u]['y'])
                    line_coords[-1] = (clusters_gdf.loc[v]['x'], clusters_gdf.loc[v]['y'])

        elif ((u is None) & (v is None)):  # maintain old_u and old_v
                u = old_u
                v = old_v
        elif ((u is None) & (v != None)) : # maintain old_u
                u = old_u
                if clusters_gdf.loc[v].keep == False: v = old_v
                else: line_coords[-1] = (clusters_gdf.loc[v]['x'], clusters_gdf.loc[v]['y'])

        else: #(( u =! None) & (v == None) !: # maintain old_v
                v = old_v
                if clusters_gdf.loc[u].keep == False: u = old_u
                else: line_coords[0] = (clusters_gdf.loc[u]['x'], clusters_gdf.loc[u]['y'])

        gline = (LineString([coor for coor in line_coords]))
        if u == v: 
            edges_gdf.drop(row.Index, axis = 0, inplace = True)
            continue
            
        edges_gdf.at[row.Index,"u"] = u
        edges_gdf.at[row.Index,"v"] = v
        edges_gdf.at[row.Index,"geometry"] = gline

    edges_gdf.drop(['old_u', 'old_v'], axis = 1, inplace=True)
    edges_gdf['u'] = edges_gdf['u'].astype(int)
    edges_gdf['v'] = edges_gdf['v'].astype(int)
    nodes_gdf['x'] = nodes_gdf['x'].astype(float)
    nodes_gdf['y'] = nodes_gdf['y'].astype(float)
       
    for row in clusters_gdf.itertuples():
        if row[ix_check] != True: continue
        oldIDs = list(nodes_gdf[nodes_gdf.cluster == row.Index]['oldIDs'])
        oldIDs = [item for sublist in oldIDs for item in sublist]
               
        nodes_gdf.at[row.Index, 'x'] = row[ix_x]
        nodes_gdf.at[row.Index, 'y'] = row[ix_y]
        nodes_gdf.at[row.Index, 'geometry'] = row[ix_centroid]
        nodes_gdf.at[row.Index, 'nodeID'] = row.Index
        nodes_gdf.at[row.Index, 'oldIDs'] = oldIDs
        nodes_gdf.at[row.Index, 'cluster'] = None
        
    nodes_gdf['nodeID'] = nodes_gdf.nodeID.astype(int)
    edges_gdf.drop(['clus_u','clus_v', 'clus_uR', 'clus_vR'], axis = 1, inplace = True)
    nodes_gdf, edges_gdf = snf.correct_edges(nodes_gdf, edges_gdf)
    nodes_gdf, edges_gdf = snf.clean_network(nodes_gdf, edges_gdf, 
                                             update_counts = update_counts, dead_ends = True, detect_islands = False)
    print("Done") 
    return(nodes_gdf, edges_gdf)

def iscontinuation(ix_lineA, ix_lineB, edges_gdf):
    
    nameA = edges_gdf.loc[ix_lineA]['name']
    nameB = edges_gdf.loc[ix_lineB]['name']
    glineA = edges_gdf.loc[ix_lineA]['geometry']
    glineB = edges_gdf.loc[ix_lineB]['geometry']
    
    if nameA == nameB:
        if perpendicular(glineA, glineB) == False: return True
        elif (perpendicular(glineA, glineB) == True) & (parallel(glineA, glineB, hard = True)): return True
        else: return False
    else:
        if (parallel(glineA, glineB, hard = False) & (perpendicular(glineA, glineB) == False)
        | parallel(glineA, glineB, hard = True)): return True
        else: return False
                     
def assign_vis(nodes_gdf, nodes_or):
    
    nodes_gdf = nodes_gdf.copy()
    nodes_or.set_index('nodeID', drop = False, inplace = True, append = False)
    del nodes_or.index.name
    
    ix_old = nodes_gdf.columns.get_loc("oldIDs")+1 
    ix_id = nodes_gdf.columns.get_loc("nodeID")+1 
    ix_ll = nodes_gdf.columns.get_loc("loc_land")+1  
    ix_ls = nodes_gdf.columns.get_loc("loc_scor")+1 
    ix_dl = nodes_gdf.columns.get_loc("dist_land")+1   
    ix_ds = nodes_gdf.columns.get_loc("dist_scor")+1   
    ix_an = nodes_gdf.columns.get_loc("anchors")+1   
    ix_da = nodes_gdf.columns.get_loc("distances")+1   

    for row in nodes_gdf.itertuples():      
        if (len(row[ix_old]) == 1) & (row[ix_old][0] == row[ix_id]): continue
        elif len(row[ix_old]) == 1: print('check', row.Index)
        else:           
            oldIDs = row[ix_old]
            loc_land =row[ix_ll]
            loc_scor = row[ix_ls]
            dist_land = row[ix_dl]
            dist_scor = row[ix_ds]
            anchors = row[ix_an]
            distances = row[ix_da]

            if type(loc_land) == float: loc_land = []
            else: loc_land = ast.literal_eval(row[ix_ll])
            if type(loc_scor) == float: loc_scor = []
            else: loc_scor = ast.literal_eval(row[ix_ls])   
            if type(dist_land) == float: dist_land = []
            else: dist_land = ast.literal_eval(row[ix_dl])       
            if type(dist_scor) == float: dist_scor = []
            else: dist_scor = ast.literal_eval(row[ix_ds])      
            if type(anchors) == float: anchors = []
            else:anchors = ast.literal_eval(row[ix_an])       
            if type(distances) == float: distances = []
            else:  distances = ast.literal_eval(row[ix_da])     
            
            if type(loc_land) != list: loc_land = []
            if type(loc_scor) != list: loc_scor = []
            if type(dist_land) != list: dist_land = []
            if type(dist_scor) != list: dist_scor = []
            if type(anchors) != list: anchors = []
            if type(distances) != list: distances = []
            
            for i in oldIDs:
                series = nodes_or.loc[i]
                loc_land_tmp = ast.literal_eval(series["loc_land"])
                loc_scor_tmp = ast.literal_eval(series["loc_scor"])
                dist_land_tmp = ast.literal_eval(series["dist_land"])
                dist_scor_tmp = ast.literal_eval(series["dist_scor"])
                anchors_tmp  = ast.literal_eval(series["anchors"])
                distances_tmp  = ast.literal_eval(series["distances"])
                
                if type(loc_land_tmp) is list: loc_land = loc_land + loc_land_tmp
                if type(loc_scor_tmp) is list: loc_scor = loc_scor + loc_scor_tmp
                if type(dist_land_tmp) is list: dist_land = dist_land + dist_land_tmp
                if type(dist_scor_tmp) is list: dist_scor = dist_scor + dist_scor_tmp
                if type(anchors_tmp) is list: anchors = anchors + anchors_tmp
                if type(distances_tmp) is list: distances = distances + distances_tmp

            if len(loc_land) > 0: 
                nodes_gdf.at[row.Index,"loc_land"] = loc_land
                nodes_gdf.at[row.Index,"loc_scor"] = loc_scor
            else: 
                nodes_gdf.at[row.Index,"loc_land"] = None
                nodes_gdf.at[row.Index,"loc_scor"] = None
            
            if len(dist_land) > 0: 
                while ((len(str(dist_land)) > 254) | (len(str(dist_scor)) > 254)):
                    del dist_land[-1]
                    del dist_scor[-1]    
                    
                nodes_gdf.at[row.Index,"dist_land"] = dist_land
                nodes_gdf.at[row.Index,"dist_scor"] = dist_scor
            else: 
                nodes_gdf.at[row.Index,"dist_land"] = None
                nodes_gdf.at[row.Index,"dist_scor"] = None
          
            if len(anchors) > 0: 
                while ((len(str(anchors)) > 254) | (len(str(distances)) > 254)):
                    del anchors[-1]
                    del distances[-1] 
                nodes_gdf.at[row.Index,"anchors"] = anchors
                nodes_gdf.at[row.Index,"distances"] = distances
            else: 
                nodes_gdf.at[row.Index,"anchors"] = None              
                nodes_gdf.at[row.Index,"distances"] = None
                
    return(nodes_gdf)

def assign_centrality(nodes_gdf, nodes_or, columns):
    
    nodes_gdf = nodes_gdf.copy()
    nodes_or.set_index('nodeID', drop = False, inplace = True, append = False)
    del nodes_or.index.name
    index_old = nodes_gdf.columns.get_loc("oldIDs")+1 
    index_Bc = nodes_gdf.columns.get_loc(columns[0])+1  

    for row in nodes_gdf.itertuples(): 
        if np.isnan(row[index_Bc]) == True:
            series = nodes_or.loc[row[index_old][0]]
            for i in columns: nodes_gdf.at[row.Index, i] = series[i]        
        else: continue
            
    return nodes_gdf
  
         
    
    
    
    
    
    
