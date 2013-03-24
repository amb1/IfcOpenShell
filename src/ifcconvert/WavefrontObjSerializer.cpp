/********************************************************************************
 *                                                                              *
 * This file is part of IfcOpenShell.                                           *
 *                                                                              *
 * IfcOpenShell is free software: you can redistribute it and/or modify         *
 * it under the terms of the Lesser GNU General Public License as published by  *
 * the Free Software Foundation, either version 3.0 of the License, or          *
 * (at your option) any later version.                                          *
 *                                                                              *
 * IfcOpenShell is distributed in the hope that it will be useful,              *
 * but WITHOUT ANY WARRANTY; without even the implied warranty of               *
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the                 *
 * Lesser GNU General Public License for more details.                          *
 *                                                                              *
 * You should have received a copy of the Lesser GNU General Public License     *
 * along with this program. If not, see <http://www.gnu.org/licenses/>.         *
 *                                                                              *
 ********************************************************************************/

#include "../ifcconvert/SurfaceStyle.h"

#include "WavefrontOBJSerializer.h"

bool WaveFrontOBJSerializer::ready() {
	return obj_stream.is_open() && mtl_stream.is_open();
}

void WaveFrontOBJSerializer::writeHeader() {
	obj_stream << "# File generated by IfcOpenShell " << IFCOPENSHELL_VERSION << std::endl;
#ifdef WIN32
	const char dir_separator = '\\';
#else
	const char dir_separator = '/';
#endif
	std::string mtl_basename = mtl_filename;
	std::string::size_type slash = mtl_basename.find_last_of(dir_separator);
	if (slash != std::string::npos) {
		mtl_basename = mtl_basename.substr(slash+1);
	}
	obj_stream << "mtllib " << mtl_basename << std::endl;
	mtl_stream << "# File generated by IfcOpenShell " << IFCOPENSHELL_VERSION << std::endl;	
}

void WaveFrontOBJSerializer::writeMaterial(const SurfaceStyle& style) {			
	mtl_stream << "newmtl " << style.Name() << std::endl
				<< "Kd " << style.Diffuse().R()  << " " << style.Diffuse().G()  << " " << style.Diffuse().B()  << std::endl
				<< "Ks " << style.Specular().R() << " " << style.Specular().G() << " " << style.Specular().B() << std::endl
				<< "Ka " << style.Ambient().R()  << " " << style.Ambient().G()  << " " << style.Ambient().B()  << std::endl
				<< "Ns " << style.Specularity()  << std::endl
				<< "Tr " << style.Transparency() << std::endl
				<< "d "  << style.Transparency() << std::endl
				<< "D "  << style.Transparency() << std::endl;			
}

void WaveFrontOBJSerializer::writeTesselated(const IfcGeomObjects::IfcGeomObject* o) {
	const std::string name = o->name.empty() ? o->guid : o->name;
	obj_stream << "g " << name << std::endl;
	obj_stream << "s 1" << std::endl;
	obj_stream << "usemtl " << o->type << std::endl;
	if (materials.find(o->type) == materials.end()) {
		writeMaterial(GetDefaultMaterial(o->type));
		materials.insert(o->type);
	}
	const int vcount = o->mesh->verts.size() / 3;
	for ( IfcGeomObjects::FltIt it = o->mesh->verts.begin(); it != o->mesh->verts.end(); ) {
		const double x = *(it++);
		const double y = *(it++);
		const double z = *(it++);
		obj_stream << "v " << x << " " << y << " " << z << std::endl;
	}
	for ( IfcGeomObjects::FltIt it = o->mesh->normals.begin(); it != o->mesh->normals.end(); ) {
		const double x = *(it++);
		const double y = *(it++);
		const double z = *(it++);
		obj_stream << "vn " << x << " " << y << " " << z << std::endl;
	}
	for ( IfcGeomObjects::IntIt it = o->mesh->faces.begin(); it != o->mesh->faces.end(); ) {
		const int v1 = *(it++)+vcount_total;
		const int v2 = *(it++)+vcount_total;
		const int v3 = *(it++)+vcount_total;
		obj_stream << "f " << v1 << "//" << v1 << " " << v2 << "//" << v2 << " " << v3 << "//" << v3 << std::endl;
	}
    vcount_total += vcount;
}
