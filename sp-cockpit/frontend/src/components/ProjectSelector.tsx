import { createContext, useContext, useEffect, useState } from "react";
import type { ProjectInfo } from "../types/api";
import { api } from "../api/client";

interface ProjectContextValue {
  projects: ProjectInfo[];
  selectedProject: ProjectInfo | null;
  setSelectedProject: (p: ProjectInfo) => void;
}

const ProjectContext = createContext<ProjectContextValue>({
  projects: [],
  selectedProject: null,
  setSelectedProject: () => {},
});

export function useProject(): ProjectContextValue {
  return useContext(ProjectContext);
}

const LS_KEY = "selectedProject";

export function ProjectProvider({ children }: { children: React.ReactNode }) {
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [selectedProject, setSelectedProjectState] = useState<ProjectInfo | null>(null);

  useEffect(() => {
    api.projects().then((list) => {
      setProjects(list);
      const saved = localStorage.getItem(LS_KEY);
      const match = list.find((p) => p.name === saved) ?? list[0] ?? null;
      setSelectedProjectState(match);
    }).catch(() => {});
  }, []);

  const setSelectedProject = (p: ProjectInfo) => {
    localStorage.setItem(LS_KEY, p.name);
    setSelectedProjectState(p);
  };

  return (
    <ProjectContext.Provider value={{ projects, selectedProject, setSelectedProject }}>
      {children}
    </ProjectContext.Provider>
  );
}

export default function ProjectSelector() {
  const { projects, selectedProject, setSelectedProject } = useProject();

  if (projects.length <= 1) return null;

  return (
    <select
      className="text-sm border rounded px-2 py-1 text-slate-700 bg-white"
      value={selectedProject?.name ?? ""}
      onChange={(e) => {
        const p = projects.find((x) => x.name === e.target.value);
        if (p) setSelectedProject(p);
      }}
    >
      {projects.map((p) => (
        <option key={p.name} value={p.name}>{p.name}</option>
      ))}
    </select>
  );
}
