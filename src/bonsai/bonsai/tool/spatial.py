# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import annotations
import bpy
import bmesh
import shapely
import shapely.ops
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import ifcopenshell.util.shape_builder
import ifcopenshell.util.type
import ifcopenshell.util.unit
import bonsai.core.type
import bonsai.core.tool
import bonsai.core.root
import bonsai.core.spatial
import bonsai.core.geometry
import bonsai.tool as tool
import json
from math import pi
from mathutils import Vector, Matrix
from shapely import Polygon
from typing import Generator, Optional, Union, Literal, List


class Spatial(bonsai.core.tool.Spatial):
    @classmethod
    def can_contain(cls, container: ifcopenshell.entity_instance, element_obj: Union[bpy.types.Object, None]) -> bool:
        element = tool.Ifc.get_entity(element_obj)
        if not element:
            return False
        if tool.Ifc.get_schema() == "IFC2X3":
            if not container.is_a("IfcSpatialStructureElement"):
                return False
        else:
            if not container.is_a("IfcSpatialStructureElement") and not container.is_a(
                "IfcExternalSpatialStructureElement"
            ):
                return False
        if not hasattr(element, "ContainedInStructure"):
            return False
        return True

    @classmethod
    def can_reference(
        cls, structure: Union[ifcopenshell.entity_instance, None], element: Union[ifcopenshell.entity_instance, None]
    ) -> bool:
        if not structure or not element:
            return False
        if tool.Ifc.get_schema() == "IFC2X3":
            if not structure.is_a("IfcSpatialStructureElement"):
                return False
        else:
            if not structure.is_a("IfcSpatialElement"):
                return False
        if not hasattr(element, "ReferencedInStructures"):
            return False
        return True

    @classmethod
    def disable_editing(cls, obj: bpy.types.Object) -> None:
        obj.BIMObjectSpatialProperties.is_editing = False

    @classmethod
    def duplicate_object_and_data(cls, obj: bpy.types.Object) -> bpy.types.Object:
        new_obj = obj.copy()
        if obj.data:
            new_obj.data = obj.data.copy()
        return new_obj

    @classmethod
    def enable_editing(cls, obj: bpy.types.Object) -> None:
        obj.BIMObjectSpatialProperties.is_editing = True
        obj.BIMObjectSpatialProperties.relating_container_object = None

    @classmethod
    def get_container(cls, element: ifcopenshell.entity_instance) -> Union[ifcopenshell.entity_instance, None]:
        return ifcopenshell.util.element.get_container(element)

    @classmethod
    def get_decomposed_elements(cls, container: ifcopenshell.entity_instance) -> list[ifcopenshell.entity_instance]:
        return ifcopenshell.util.element.get_decomposition(container)

    @classmethod
    def get_object_matrix(cls, obj: bpy.types.Object) -> Matrix:
        return obj.matrix_world

    @classmethod
    def get_relative_object_matrix(cls, target_obj: bpy.types.Object, relative_to_obj: bpy.types.Object) -> Matrix:
        return relative_to_obj.matrix_world.inverted() @ target_obj.matrix_world

    @classmethod
    def run_root_copy_class(cls, obj: bpy.types.Object) -> ifcopenshell.entity_instance:
        return bonsai.core.root.copy_class(tool.Ifc, tool.Collector, tool.Geometry, tool.Root, obj=obj)

    @classmethod
    def run_spatial_assign_container(
        cls, container: ifcopenshell.entity_instance, element_obj: bpy.types.Object
    ) -> Union[ifcopenshell.entity_instance, None]:
        return bonsai.core.spatial.assign_container(
            tool.Ifc, tool.Collector, tool.Spatial, container=container, element_obj=element_obj
        )

    @classmethod
    def run_spatial_import_spatial_decomposition(cls) -> None:
        return bonsai.core.spatial.import_spatial_decomposition(tool.Spatial)

    @classmethod
    def select_object(cls, obj: bpy.types.Object) -> None:
        tool.Blender.select_object(obj)

    @classmethod
    def set_active_object(cls, obj: bpy.types.Object) -> None:
        tool.Blender.set_active_object(obj)

    @classmethod
    def set_relative_object_matrix(
        cls, target_obj: bpy.types.Object, relative_to_obj: bpy.types.Object, matrix: Matrix
    ) -> None:
        target_obj.matrix_world = relative_to_obj.matrix_world @ matrix

    @classmethod
    def select_products(cls, products: list[ifcopenshell.entity_instance], unhide: bool = False) -> None:
        bpy.ops.object.select_all(action="DESELECT")
        for product in products:
            obj = tool.Ifc.get_object(product)
            if obj and bpy.context.view_layer.objects.get(obj.name):
                if unhide:
                    obj.hide_set(False)
                obj.select_set(True)

    @classmethod
    def filter_products(
        cls, products: list[ifcopenshell.entity_instance], action: Literal["select", "isolate", "unhide", "hide"]
    ) -> None:
        objects = [obj for product in products if (obj := tool.Ifc.get_object(product))]
        if action == "select":
            [obj.select_set(True) for obj in objects]
        elif action == "isolate":
            [obj.hide_set(False) for obj in objects if bpy.context.view_layer.objects.get(obj.name)]
            [
                obj.hide_set(True)
                for obj in bpy.context.visible_objects
                if not obj in objects and bpy.context.view_layer.objects.get(obj.name)
            ]  # this is slow
        elif action == "unhide":
            [obj.hide_set(False) for obj in objects if bpy.context.view_layer.objects.get(obj.name)]
        elif action == "hide":
            [obj.hide_set(True) for obj in objects if bpy.context.view_layer.objects.get(obj.name)]

    @classmethod
    def deselect_objects(cls) -> None:
        [obj.select_set(False) for obj in bpy.context.selected_objects]

    @classmethod
    def show_scene_objects(cls) -> None:
        [
            obj.hide_set(False)
            for obj in bpy.data.scenes["Scene"].objects
            if bpy.context.view_layer.objects.get(obj.name)
        ]

    @classmethod
    def get_selected_products(cls) -> Generator[ifcopenshell.entity_instance, None, None]:
        for obj in bpy.context.selected_objects:
            entity = tool.Ifc.get_entity(obj)
            if entity and entity.is_a("IfcProduct"):
                yield entity

    @classmethod
    def get_selected_product_types(cls) -> Generator[ifcopenshell.entity_instance, None, None]:
        for obj in tool.Blender.get_selected_objects():
            entity = tool.Ifc.get_entity(obj)
            if entity and entity.is_a("IfcTypeProduct"):
                yield entity

    @classmethod
    def copy_xy(cls, src_obj: bpy.types.Object, destination_obj: bpy.types.Object) -> None:
        src_obj.location.xy = destination_obj.location.xy

    @classmethod
    def load_contained_elements(cls) -> None:
        props = bpy.context.scene.BIMSpatialDecompositionProperties
        props.elements.clear()
        if not (container := props.active_container):
            return

        container = tool.Ifc.get().by_id(container.ifc_definition_id)

        results = {}
        if props.should_include_children:
            elements = ifcopenshell.util.element.get_decomposition(container, is_recursive=True)
        else:
            elements = ifcopenshell.util.element.get_contained(container)
        for element in elements:
            if not element.is_a("IfcElement"):
                continue
            element_type = ifcopenshell.util.element.get_type(element)
            ifc_class = element.is_a()
            ifc_definition_id = element_type.id() if element_type else 0
            type_name = element_type.Name or "Unnamed" if element_type else "Untyped"
            results.setdefault(ifc_class, {}).setdefault(ifc_definition_id, {"total": 0, "type_name": type_name})
            results[ifc_class][ifc_definition_id]["total"] += 1

        total_elements = 0
        for ifc_class in sorted(results.keys()):
            new = props.elements.add()
            new.name = ifc_class
            new.is_class = True
            total = 0
            for ifc_definition_id in sorted(
                results[ifc_class].keys(), key=lambda x: results[ifc_class][x]["type_name"]
            ):
                new2 = props.elements.add()
                new2.is_type = True
                new2.name = results[ifc_class][ifc_definition_id]["type_name"]
                new2.total = results[ifc_class][ifc_definition_id]["total"]
                new2.ifc_definition_id = ifc_definition_id
                total += new2.total
            new.total = total
            total_elements += total

        props.total_elements = total_elements

    @classmethod
    def filter_elements_by_class(cls, elements: List[ifcopenshell.entity_instance], ifc_class: str):
        return [e for e in elements if e.is_a(ifc_class)]

    @classmethod
    def filter_elements_by_relating_type(
        cls, elements: List[ifcopenshell.entity_instance], relating_type: ifcopenshell.entity_instance
    ):
        return [e for e in elements if ifcopenshell.util.element.get_type(e) == relating_type]

    @classmethod
    def filter_elements_by_untyped(cls, elements: List[ifcopenshell.entity_instance]):
        return [e for e in elements if not ifcopenshell.util.element.get_type(e)]

    @classmethod
    def import_spatial_decomposition(cls) -> None:
        props = bpy.context.scene.BIMSpatialDecompositionProperties
        previous_container_index = props.active_container_index
        props.containers.clear()
        cls.contracted_containers = json.loads(props.contracted_containers)
        cls.import_spatial_element(tool.Ifc.get().by_type("IfcProject")[0], 0)
        props.active_container_index = min(previous_container_index, len(props.containers) - 1)

    @classmethod
    def import_spatial_element(cls, element: ifcopenshell.entity_instance, level_index: int) -> None:
        if not element.is_a("IfcProject") and not tool.Root.is_spatial_element(element):
            return
        props = bpy.context.scene.BIMSpatialDecompositionProperties
        new = props.containers.add()
        new.ifc_class = element.is_a()
        new.name = element.Name or "Unnamed"
        new.description = element.Description or ""
        new.long_name = element.LongName or ""
        if not element.is_a("IfcProject"):
            ifc_file = tool.Ifc.get()
            si_conversion = ifcopenshell.util.unit.calculate_unit_scale(ifc_file)
            new.elevation = ifcopenshell.util.placement.get_storey_elevation(element) * si_conversion
        new.is_expanded = element.id() not in cls.contracted_containers
        new.level_index = level_index
        children = ifcopenshell.util.element.get_parts(element)
        new.has_children = bool(children)
        new.ifc_definition_id = element.id()
        if new.is_expanded:
            for child in children or []:
                cls.import_spatial_element(child, level_index + 1)

    @classmethod
    def edit_container_attributes(cls, entity: ifcopenshell.entity_instance) -> None:
        # TODO
        obj = tool.Ifc.get_object(entity)
        bonsai.core.geometry.edit_object_placement(tool.Ifc, tool.Geometry, tool.Surveyor, obj=obj)
        name = bpy.context.scene.BIMSpatialDecompositionProperties.container_name
        if name != entity.Name:
            cls.edit_container_name(entity, name)

    @classmethod
    def edit_container_name(cls, container: ifcopenshell.entity_instance, name: str) -> None:
        tool.Ifc.run("attribute.edit_attributes", product=container, attributes={"Name": name})

    @classmethod
    def get_active_container(cls) -> Union[ifcopenshell.entity_instance, None]:
        props = bpy.context.scene.BIMSpatialDecompositionProperties
        if props.active_container_index < len(props.containers):
            container = tool.Ifc.get().by_id(props.containers[props.active_container_index].ifc_definition_id)
            return container

    @classmethod
    def contract_container(cls, container: ifcopenshell.entity_instance) -> None:
        props = bpy.context.scene.BIMSpatialDecompositionProperties
        contracted_containers = json.loads(props.contracted_containers)
        contracted_containers.append(container.id())
        props.contracted_containers = json.dumps(contracted_containers)

    @classmethod
    def expand_container(cls, container: ifcopenshell.entity_instance) -> None:
        props = bpy.context.scene.BIMSpatialDecompositionProperties
        contracted_containers = json.loads(props.contracted_containers)
        contracted_containers.remove(container.id())
        props.contracted_containers = json.dumps(contracted_containers)

    # HERE STARTS SPATIAL TOOL

    @classmethod
    def is_bounding_class(cls, visible_element: ifcopenshell.entity_instance) -> bool:
        for ifc_class in ["IfcWall", "IfcColumn", "IfcMember", "IfcVirtualElement", "IfcPlate"]:
            if visible_element.is_a(ifc_class):
                return True
        return False

    @classmethod
    def get_space_polygon_from_context_visible_objects(cls, x: float, y: float) -> Union[shapely.Polygon, None]:
        boundary_lines = cls.get_boundary_lines_from_context_visible_objects()
        unioned_boundaries = shapely.union_all(shapely.GeometryCollection(boundary_lines))
        closed_polygons = shapely.polygonize(unioned_boundaries.geoms)
        space_polygon = None
        for polygon in closed_polygons.geoms:
            if shapely.contains_xy(polygon, x, y):
                space_polygon = shapely.force_3d(polygon)
        return space_polygon

    @classmethod
    def debug_shape(cls, foo: shapely.Polygon) -> None:
        coords = [(p[0], p[1], 0) for p in foo.exterior.coords]
        mesh = bpy.data.meshes.new(name="NewMesh")
        bm = bmesh.new()
        for coord in coords:
            bm.verts.new(coord)
        bm.verts.ensure_lookup_table()
        bm.faces.new(bm.verts)
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new("NewObject", mesh)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.update()

    @classmethod
    def debug_line(cls, start: Vector, end: Vector) -> None:
        coords = [start, end]
        mesh = bpy.data.meshes.new(name="NewMesh")
        bm = bmesh.new()
        for coord in coords:
            bm.verts.new(coord)
        bm.verts.ensure_lookup_table()
        bm.edges.new(bm.verts)
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new("NewLine", mesh)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.update()

    @classmethod
    def get_boundary_lines_from_context_visible_objects(cls) -> list[shapely.LineString]:
        calculation_rl = bpy.context.scene.BIMModelProperties.rl3
        container = tool.Root.get_default_container()
        container_obj = tool.Ifc.get_object(container)
        cut_point = container_obj.matrix_world.translation.copy() + Vector((0, 0, calculation_rl))
        cut_normal = Vector((0, 0, 1))
        boundary_lines = []

        for obj in bpy.context.visible_objects:
            visible_element = tool.Ifc.get_entity(obj)

            if (
                not visible_element
                or obj.type != "MESH"
                or not cls.is_bounding_class(visible_element)
                or not tool.Drawing.is_intersecting_plane(obj, cut_point, cut_normal)
            ):
                continue

            old_mesh = obj.data
            assert isinstance(old_mesh, bpy.types.Mesh)
            if visible_element.HasOpenings:
                new_mesh = cls.get_gross_mesh_from_element(visible_element)
            else:
                new_mesh = old_mesh.copy()
            obj.data = new_mesh

            # Boundary objects are likely triangulated. If a triangulated quad
            # is bisected by our plane, we end up with two lines instead of
            # one. This makes shapely's job much harder (since shapely is very
            # exact with its coordinates). As a result, let's limited dissolve
            # prior to bisecting.
            bm = bmesh.new()
            bm.from_mesh(new_mesh)
            bmesh.ops.dissolve_limit(bm, angle_limit=0.02, verts=bm.verts, edges=bm.edges)
            bm.to_mesh(new_mesh)
            new_mesh.update()
            bm.free()

            local_cut_point = obj.matrix_world.inverted() @ cut_point
            local_cut_normal = obj.matrix_world.inverted().to_quaternion() @ cut_normal
            verts, edges = tool.Drawing.bisect_mesh_with_plane(obj, local_cut_point, local_cut_normal)

            # Restore the original mesh
            obj.data = old_mesh
            bpy.data.meshes.remove(new_mesh)

            for edge in edges or []:
                # Rounding is necessary to ensure coincident points are coincident
                start = [round(x, 3) for x in verts[edge[0]]]
                end = [round(x, 3) for x in verts[edge[1]]]
                if start == end:
                    continue
                # Extension by 50mm is necessary to ensure lines overlap with other diagonal lines
                # This also closes small but likely irrelevant gaps for space generation.
                start, end = tool.Drawing.extend_line(start, end, 0.05)
                boundary_lines.append(shapely.LineString([start, end]))

        return boundary_lines

    @classmethod
    def get_gross_mesh_from_element(cls, visible_element: ifcopenshell.entity_instance) -> bpy.types.Mesh:
        gross_settings = ifcopenshell.geom.settings()
        gross_settings.set("disable-opening-subtractions", True)
        new_mesh = cls.create_mesh_from_shape(ifcopenshell.geom.create_shape(gross_settings, visible_element))
        return new_mesh

    @classmethod
    def create_mesh_from_shape(cls, shape: ifcopenshell.geom.ShapeElementType) -> bpy.types.Mesh:
        geometry = shape.geometry
        mesh = bpy.data.meshes.new("tmp")
        verts = geometry.verts
        if geometry.faces:
            num_vertices = len(verts) // 3
            total_faces = len(geometry.faces)
            loop_start = range(0, total_faces, 3)
            num_loops = total_faces // 3
            loop_total = [3] * num_loops
            num_vertex_indices = len(geometry.faces)

            mesh.vertices.add(num_vertices)
            mesh.vertices.foreach_set("co", verts)
            mesh.loops.add(num_vertex_indices)
            mesh.loops.foreach_set("vertex_index", geometry.faces)
            mesh.polygons.add(num_loops)
            mesh.polygons.foreach_set("loop_start", loop_start)
            mesh.polygons.foreach_set("loop_total", loop_total)
            mesh.polygons.foreach_set("use_smooth", [0] * total_faces)
            mesh.update()
        return mesh

    @classmethod
    def get_x_y_z_h_mat_from_obj(cls, obj: bpy.types.Object) -> tuple[float, float, float, float, Matrix]:
        mat = obj.matrix_world
        local_bbox_center = 0.125 * sum((Vector(b) for b in obj.bound_box), Vector())
        global_bbox_center = mat @ local_bbox_center
        x = global_bbox_center.x
        y = global_bbox_center.y
        z = (mat @ Vector(obj.bound_box[0])).z

        h = obj.dimensions.z
        return x, y, z, h, mat

    @classmethod
    def get_x_y_z_h_mat_from_cursor(cls) -> tuple[float, float, float, float, Matrix]:
        x, y, z = bpy.context.scene.cursor.location.xyz
        if container := tool.Root.get_default_container():
            if container_obj := tool.Ifc.get_object(container):
                z = container_obj.matrix_world.translation.z
        mat = Matrix()
        h = 3
        return x, y, z, h, mat

    @classmethod
    def get_union_shape_from_selected_objects(cls) -> Polygon:
        selected_objects = bpy.context.selected_objects
        boundary_elements = cls.get_boundary_elements(selected_objects)
        polys = cls.get_polygons(boundary_elements)
        converted_tolerance = cls.get_converted_tolerance(tolerance_si=0.03)
        union = shapely.ops.unary_union(polys).buffer(
            converted_tolerance,
            cap_style=shapely.constructive.BufferCapStyle.flat,
            join_style=shapely.constructive.BufferJoinStyle.mitre,
        )
        union = cls.get_purged_inner_holes_poly(
            union_geom=union, min_area=cls.get_converted_tolerance(tolerance_si=0.1)
        )
        return union

    @classmethod
    def get_boundary_elements(cls, selected_objects: list[bpy.types.Object]) -> list[ifcopenshell.entity_instance]:
        boundary_elements = []
        for obj in selected_objects:
            subelement = tool.Ifc.get_entity(obj)
            if subelement.is_a("IfcWall") or subelement.is_a("IfcColumn"):
                boundary_elements.append(subelement)
        return boundary_elements

    @classmethod
    def get_polygons(cls, boundary_elements: list[ifcopenshell.entity_instance]) -> list[Polygon]:
        polys = []
        for boundary_element in boundary_elements:
            obj = tool.Ifc.get_object(boundary_element)
            if not obj:
                continue
            points = []
            base = cls.get_obj_base_points(obj)
            for index in ["low_left", "low_right", "high_right", "high_left"]:
                point = base[index]
                points.append(point)

            polys.append(Polygon(points))
        return polys

    @classmethod
    def get_obj_base_points(cls, obj: bpy.types.Object) -> dict[str, tuple[float, float]]:
        si_conversion = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())
        bbox_ws = [obj.matrix_world @ Vector(v) / si_conversion for v in obj.bound_box]
        return {
            "low_left": (bbox_ws[0].x, bbox_ws[0].y),
            "high_left": (bbox_ws[3].x, bbox_ws[3].y),
            "low_right": (bbox_ws[4].x, bbox_ws[4].y),
            "high_right": (bbox_ws[7].x, bbox_ws[7].y),
        }

    @classmethod
    def get_converted_tolerance(cls, tolerance_si: float) -> float:
        model = tool.Ifc.get()
        si_conversion = ifcopenshell.util.unit.calculate_unit_scale(model)
        return tolerance_si / si_conversion

    @classmethod
    def get_purged_inner_holes_poly(cls, union_geom: Polygon, min_area: float) -> Polygon:
        interiors_list = []

        if union_geom.geom_type == "MultiPolygon":
            for poly in union_geom.geoms:
                interiors_list = cls.get_poly_valid_interior_list(
                    poly=poly, min_area=min_area, interiors_list=interiors_list
                )

            new_poly = Polygon(poly.exterior.coords, holes=interiors_list)

        if union_geom.geom_type == "Polygon":
            interiors_list = cls.get_poly_valid_interior_list(
                poly=union_geom, min_area=min_area, interiors_list=interiors_list
            )
            new_poly = Polygon(union_geom.exterior.coords, holes=interiors_list)

        return new_poly

    @classmethod
    def get_poly_valid_interior_list(cls, poly: Polygon, min_area: float, interiors_list: list[shapely.LinearRing]):
        for interior in poly.interiors:
            p = Polygon(interior)
            if p.area >= min_area:
                interiors_list.append(interior)
        return interiors_list

    @classmethod
    def get_buffered_poly_from_linear_ring(cls, linear_ring: shapely.LinearRing) -> Polygon:
        poly = Polygon(linear_ring)
        converted_tolerance = cls.get_converted_tolerance(tolerance_si=0.03)
        poly = poly.buffer(
            converted_tolerance,
            single_sided=True,
            cap_style=shapely.BufferCapStyle.flat,
            join_style=shapely.BufferJoinStyle.mitre,
        )
        return poly

    @classmethod
    def get_bmesh_from_polygon(cls, poly: Polygon, h: float) -> bmesh.types.BMesh:
        mat = Matrix()
        bm = bmesh.new()
        bm.verts.index_update()
        bm.edges.index_update()

        mat_invert = mat.inverted()
        si_conversion = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())
        new_verts = [
            bm.verts.new(mat_invert @ (Vector([v[0], v[1], 0]) * si_conversion)) for v in poly.exterior.coords[0:-1]
        ]
        [bm.edges.new((new_verts[i], new_verts[i + 1])) for i in range(len(new_verts) - 1)]
        bm.edges.new((new_verts[len(new_verts) - 1], new_verts[0]))

        bm.verts.index_update()
        bm.edges.index_update()

        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        bmesh.ops.triangle_fill(bm, edges=bm.edges)
        bmesh.ops.dissolve_limit(bm, angle_limit=pi / 180 * 5, verts=bm.verts, edges=bm.edges)

        if h != 0:
            extrusion = bmesh.ops.extrude_face_region(bm, geom=bm.faces)
            extruded_verts = [g for g in extrusion["geom"] if isinstance(g, bmesh.types.BMVert)]
            bmesh.ops.translate(bm, vec=[0.0, 0.0, h], verts=extruded_verts)

        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

        return bm

    @classmethod
    def get_named_obj_from_bmesh(cls, name: str, bmesh: bmesh.types.BMesh) -> bpy.types.Object:
        mesh = cls.get_named_mesh_from_bmesh(name, bmesh)
        obj = cls.get_named_obj_from_mesh(name, mesh)
        return obj

    @classmethod
    def get_named_obj_from_mesh(cls, name: str, mesh: bpy.types.Mesh) -> bpy.types.Object:
        obj = bpy.data.objects.new(name, mesh)
        return obj

    @classmethod
    def get_named_mesh_from_bmesh(cls, name: str, bmesh: bmesh.types.BMesh) -> bpy.types.Mesh:
        mesh = bpy.data.meshes.new(name=name)
        bmesh.to_mesh(mesh)
        bmesh.free()
        return mesh

    @classmethod
    def get_transformed_mesh_from_local_to_global(cls, mesh: bpy.types.Mesh) -> bpy.types.Mesh:
        active_obj = cls.get_active_obj()
        mat = active_obj.matrix_world
        mesh.transform(mat.inverted())
        mesh.update()
        return mesh

    @classmethod
    def edit_active_space_obj_from_mesh(cls, mesh: bpy.types.Mesh) -> None:
        active_obj = bpy.context.active_object
        mesh.name = active_obj.data.name
        mesh.BIMMeshProperties.ifc_definition_id = active_obj.data.BIMMeshProperties.ifc_definition_id
        tool.Geometry.change_object_data(active_obj, mesh, is_global=True)
        tool.Ifc.edit(active_obj)

    @classmethod
    def set_obj_origin_to_bboxcenter(cls, obj: bpy.types.Object) -> None:
        mat = obj.matrix_world
        inverted = mat.inverted()
        local_bbox_center = 0.125 * sum((Vector(b) for b in obj.bound_box), Vector())
        global_bbox_center = mat @ local_bbox_center

        oldLoc = obj.location
        newLoc = global_bbox_center
        diff = newLoc - oldLoc
        for vert in obj.data.vertices:
            aux_vector = mat @ vert.co
            aux_vector = aux_vector - diff
            vert.co = inverted @ aux_vector
        obj.location = newLoc

    @classmethod
    def set_obj_origin_to_bboxcenter_and_zero_elevation(cls, obj: bpy.types.Object) -> None:
        mat = obj.matrix_world
        inverted = mat.inverted()
        local_bbox_center = 0.125 * sum((Vector(b) for b in obj.bound_box), Vector())
        global_bbox_center = mat @ local_bbox_center
        global_obj_origin = global_bbox_center
        global_obj_origin.z = 0

        oldLoc = obj.location
        newLoc = global_obj_origin
        diff = newLoc - oldLoc
        for vert in obj.data.vertices:
            aux_vector = mat @ vert.co
            aux_vector = aux_vector - diff
            vert.co = inverted @ aux_vector
        obj.location = newLoc

    @classmethod
    def set_obj_origin_to_cursor_position_and_zero_elevation(cls, obj: bpy.types.Object) -> None:
        mat = obj.matrix_world
        inverted = mat.inverted()

        x, y = bpy.context.scene.cursor.location.xy
        z = 0

        oldLoc = obj.location
        newLoc = Vector((x, y, z))
        diff = newLoc - oldLoc
        for vert in obj.data.vertices:
            aux_vector = mat @ vert.co
            aux_vector = aux_vector - diff
            vert.co = inverted @ aux_vector
        obj.location = newLoc

    @classmethod
    def get_selected_objects(cls) -> list[bpy.types.Object]:
        return bpy.context.selected_objects

    @classmethod
    def get_active_obj(cls) -> Union[bpy.types.Object, None]:
        return bpy.context.active_object

    @classmethod
    def get_active_obj_z(cls) -> float:
        return bpy.context.active_object.matrix_world.translation.z

    @classmethod
    def get_active_obj_height(cls) -> float:
        height = bpy.context.active_object.dimensions.z
        return height

    @classmethod
    def get_relating_type_id(cls) -> int:
        props = bpy.context.scene.BIMModelProperties
        relating_type_id = props.relating_type_id
        return relating_type_id

    @classmethod
    def translate_obj_to_z_location(cls, obj: bpy.types.Object, z: float) -> None:
        if z != 0:
            obj.location = obj.location + Vector((0, 0, z))

    @classmethod
    def get_2d_vertices_from_obj(cls, obj: bpy.types.Object) -> list[tuple]:
        points = []
        vectors = [v.co for v in obj.data.vertices.values()]
        for vector in vectors:
            points.append(vector.xy)

        points.append(vectors[0].xy)
        return points

    @classmethod
    def get_scaled_2d_vertices(cls, points: list[Vector]) -> list[tuple[float, float]]:
        model = tool.Ifc.get()
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(model)
        _points = []
        for p in points:
            _p = list(p)
            _p[0] /= unit_scale
            _p[1] /= unit_scale
            _points.append(_p)
        return _points

    @classmethod
    def assign_swept_area_outer_curve_from_2d_vertices(cls, obj: bpy.types.Object, vertices: list[Vector]) -> None:
        body = cls.get_body_representation(obj)
        model = tool.Ifc.get()
        extrusion = tool.Model.get_extrusion(body)
        area = extrusion.SweptArea
        old_area = area.OuterCurve

        builder = ifcopenshell.util.shape_builder.ShapeBuilder(model)
        outer_curve = builder.polyline(vertices, closed=True)

        area.OuterCurve = outer_curve
        ifcopenshell.util.element.remove_deep2(tool.Ifc.get(), old_area)

    @classmethod
    def get_body_representation(cls, obj: bpy.types.Object) -> Union[ifcopenshell.entity_instance, None]:
        element = tool.Ifc.get_entity(obj)
        return ifcopenshell.util.representation.get_representation(element, "Model", "Body", "MODEL_VIEW")

    @classmethod
    def assign_ifcspace_class_to_obj(cls, obj: bpy.types.Object) -> None:
        bpy.ops.bim.assign_class(obj=obj.name, ifc_class="IfcSpace")

    @classmethod
    def assign_type_to_obj(cls, obj: bpy.types.Object) -> None:
        relating_type_id = bpy.context.scene.BIMModelProperties.relating_type_id
        relating_type = tool.Ifc.get().by_id(int(relating_type_id))
        ifc_class = relating_type.is_a()
        instance_class = ifcopenshell.util.type.get_applicable_entities(ifc_class, tool.Ifc.get().schema)[0]
        bpy.ops.bim.assign_class(obj=obj.name, ifc_class=instance_class)
        element = tool.Ifc.get_entity(obj)
        tool.Ifc.run("type.assign_type", related_objects=[element], relating_type=relating_type)

    @classmethod
    def assign_relating_type_to_element(
        cls,
        ifc: tool.Ifc,
        type: tool.Type,
        element: ifcopenshell.entity_instance,
        relating_type: ifcopenshell.entity_instance,
    ) -> None:
        bonsai.core.type.assign_type(ifc, type, element=element, type=relating_type)

    @classmethod
    def regen_obj_representation(cls, obj: bpy.types.Object, body: ifcopenshell.entity_instance) -> None:
        bonsai.core.geometry.switch_representation(
            tool.Ifc,
            tool.Geometry,
            obj=obj,
            representation=body,
            should_reload=True,
            is_global=True,
            should_sync_changes_first=False,
        )

    @classmethod
    def toggle_spaces_visibility_wired_and_textured(cls, spaces: list[ifcopenshell.entity_instance]) -> None:
        first_obj = tool.Ifc.get_object(spaces[0])
        if bpy.data.objects[first_obj.name].display_type == "TEXTURED":
            for space in spaces:
                obj = tool.Ifc.get_object(space)
                bpy.data.objects[obj.name].show_wire = True
                bpy.data.objects[obj.name].display_type = "WIRE"
            return

        elif bpy.data.objects[first_obj.name].display_type == "WIRE":
            for space in spaces:
                obj = tool.Ifc.get_object(space)
                bpy.data.objects[obj.name].show_wire = False
                bpy.data.objects[obj.name].display_type = "TEXTURED"
            return

    @classmethod
    def toggle_hide_spaces(cls, spaces: list[ifcopenshell.entity_instance]) -> None:
        first_obj = tool.Ifc.get_object(spaces[0])
        if first_obj.hide_get() == False:
            for space in spaces:
                obj = tool.Ifc.get_object(space)
                obj.hide_set(True)
            return

        elif first_obj.hide_get() == True:
            for space in spaces:
                obj = tool.Ifc.get_object(space)
                obj.hide_set(False)

    @classmethod
    def set_default_container(cls, container: ifcopenshell.entity_instance) -> None:
        bpy.context.scene.BIMSpatialDecompositionProperties.default_container = container.id()
        project = tool.Ifc.get_object(tool.Ifc.get().by_type("IfcProject")[0])
        project_collection = project.BIMObjectProperties.collection
        obj = tool.Ifc.get_object(container)
        if obj and (collection := obj.BIMObjectProperties.collection):
            for layer_collection in bpy.context.view_layer.layer_collection.children:
                if layer_collection.collection == project_collection:
                    for layer_collection2 in layer_collection.children:
                        if layer_collection2.collection == collection:
                            bpy.context.view_layer.active_layer_collection = layer_collection2
                            break

    @classmethod
    def guess_default_container(cls) -> Optional[ifcopenshell.entity_instance]:
        project = tool.Ifc.get().by_type("IfcProject")[0]
        subelement = None
        # We try to priorise the first Site > Building > Storey as a convention for vertical projects
        for subelement in ifcopenshell.util.element.get_parts(project):
            if subelement.is_a("IfcSite"):
                for subelement2 in ifcopenshell.util.element.get_parts(subelement):
                    if subelement2.is_a("IfcBuilding"):
                        for subelement3 in ifcopenshell.util.element.get_parts(subelement2):
                            if subelement3.is_a("IfcBuildingStorey"):
                                return subelement3
        if subelement:
            return subelement
        return None

    @classmethod
    def get_selected_containers(cls) -> List[ifcopenshell.entity_instance]:
        results = []
        for obj in tool.Blender.get_selected_objects():
            if (element := tool.Ifc.get_entity(obj)) and tool.Root.is_spatial_element(element):
                results.append(element)
        return results

    @classmethod
    def get_selected_objects_without_containers(cls) -> list[bpy.types.Object]:
        """Get selected objects skipping spatial elements.

        Useful for operators that are using selected objects to identify selected containers.
        Note that those operators are typically have a limitation since they can't tell
        objects to operate on from containers that should be used in the operation.

        E.g. we cannot bim.copy_to_container containers to other containers."""
        results: list[bpy.types.Object] = []
        for obj in tool.Blender.get_selected_objects():
            if (element := tool.Ifc.get_entity(obj)) and not tool.Root.is_spatial_element(element):
                results.append(obj)
        return results

    @classmethod
    def set_target_container_as_default(cls) -> None:
        if (
            (container := tool.Root.get_default_container())
            and (obj := tool.Ifc.get_object(container))
            and bpy.context.active_object
        ):
            props = bpy.context.active_object.BIMObjectSpatialProperties
            props.container_obj = obj